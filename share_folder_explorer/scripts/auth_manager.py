"""
AuthManager — 认证、Session 管理、SMB 连接注册。

连接策略：
  - 使用 smbclient.register_session() 注册凭据，smbprotocol 内部管理连接池。
  - 同一 server 可以有多个 session（不同用户），每次文件操作时按 credential 选择对应 session。
  - 切换用户时调用 smbclient.reset_connection_cache() 清除旧 session，再重新注册。
  - 不依赖 net use，无 error 1219，无盘符占用。
"""

import uuid
import datetime
import threading
import smbclient
from smbprotocol.exceptions import SMBException, SMBAuthenticationError

from .db import get_connection
from .smb_handler import SMBHandler
from .crypto_utils import encrypt_with_fernet, decrypt_with_fernet


class AuthManager:
    def __init__(self, share_path: str, domain: str = None):
        # share_path 形如 \\192.168.8.199\upload 或 //192.168.8.199/upload
        self.domain = domain

        # 规范化：统一用反斜杠，去掉首尾分隔符
        normalized = share_path.replace("/", "\\").strip("\\")
        parts = normalized.split("\\")
        if len(parts) < 2:
            raise ValueError(f"Invalid share_path: {share_path!r}")

        self.server = parts[0]   # e.g. 192.168.8.199
        self.share = parts[1]    # e.g. upload

        # 当前注册的 smbclient session 对应的 credential_id
        # smbprotocol 同一 server 同一时刻只支持一套凭据，
        # 多用户时需要切换，用锁保护。
        self._active_credential_id: int | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  内部：注册 / 切换 SMB session                                        #
    # ------------------------------------------------------------------ #

    def _register_session(self, username: str, password: str) -> None:
        """
        向 smbprotocol 注册新 session。
        调用前必须持有 self._lock。
        """
        # 先清除该 server 的旧 session
        try:
            smbclient.delete_session(self.server)
        except Exception:
            pass  # 没有旧 session 时忽略

        smb_user = f"{self.domain}\\{username}" if self.domain else username
        smbclient.register_session(
            self.server,
            username=smb_user,
            password=password,
            auth_protocol="ntlm",
        )

    def _disconnect(self) -> None:
        """断开当前 server 的所有 session。调用前必须持有 self._lock。"""
        try:
            smbclient.delete_session(self.server)
        except Exception:
            pass
        self._active_credential_id = None

    # ------------------------------------------------------------------ #
    #  登录                                                                #
    # ------------------------------------------------------------------ #

    def login(self, username: str, password: str, user_agent: str) -> str:
        with self._lock:
            # 1. 尝试注册 session 并验证连接
            try:
                self._register_session(username, password)
                # 验证：列出根目录
                handler = SMBHandler(self.server, self.share)
                handler.list_dir("/")
            except SMBAuthenticationError as e:
                self._disconnect()
                raise ValueError(f"Authentication failed: {e}")
            except SMBException as e:
                self._disconnect()
                raise ValueError(f"SMB connection failed: {e}")
            except Exception as e:
                self._disconnect()
                raise ValueError(f"Login failed: {e}")

            # 2. 加密保存凭据
            encrypted_pwd = encrypt_with_fernet(password)

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM credentials WHERE username = ?", (username,)
                )
                row = cursor.fetchone()

                if row:
                    cred_id = row["id"]
                    cursor.execute(
                        "UPDATE credentials SET encrypted_password = ? WHERE id = ?",
                        (encrypted_pwd, cred_id),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO credentials (username, encrypted_password) VALUES (?, ?)",
                        (username, encrypted_pwd),
                    )
                    cred_id = cursor.lastrowid

                # 3. 创建 session token
                token = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO sessions (token, credential_id, user_agent, last_active)
                    VALUES (?, ?, ?, ?)
                    """,
                    (token, cred_id, user_agent, datetime.datetime.now()),
                )
                conn.commit()

            self._active_credential_id = cred_id
            return token

    # ------------------------------------------------------------------ #
    #  Session 校验                                                        #
    # ------------------------------------------------------------------ #

    def validate_session(self, token: str, user_agent: str) -> dict | None:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.token, c.username, s.credential_id, s.last_active
                FROM sessions s
                JOIN credentials c ON s.credential_id = c.id
                WHERE s.token = ?
                """,
                (token,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            last_active = row["last_active"]
            if isinstance(last_active, str):
                last_active = datetime.datetime.fromisoformat(last_active)

            if datetime.datetime.now() - last_active > datetime.timedelta(hours=24):
                self.logout(token)
                return None

            cursor.execute(
                "UPDATE sessions SET last_active = ? WHERE token = ?",
                (datetime.datetime.now(), token),
            )
            conn.commit()

            return {
                "username": row["username"],
                "credential_id": row["credential_id"],
                "token": row["token"],
            }

    # ------------------------------------------------------------------ #
    #  登出                                                                #
    # ------------------------------------------------------------------ #

    def logout(self, token: str) -> None:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT credential_id FROM sessions WHERE token = ?", (token,)
            )
            row = cursor.fetchone()

        with self._lock:
            if row and row["credential_id"] == self._active_credential_id:
                self._disconnect()

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()

    # ------------------------------------------------------------------ #
    #  获取 SMBHandler（供 server.py 文件路由使用）                          #
    # ------------------------------------------------------------------ #

    def get_smb_handler(self, credential_id: int) -> SMBHandler:
        with self._lock:
            if credential_id == self._active_credential_id:
                # 当前 session 就是此用户，直接复用
                return SMBHandler(self.server, self.share)

            # 需要切换用户：从 DB 取出加密密码重新注册
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT username, encrypted_password FROM credentials WHERE id = ?",
                    (credential_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Credential not found")
                username = row["username"]
                password = decrypt_with_fernet(row["encrypted_password"])

            self._register_session(username, password)
            self._active_credential_id = credential_id
            return SMBHandler(self.server, self.share)

    # ------------------------------------------------------------------ #
    #  定时清理过期 session                                                 #
    # ------------------------------------------------------------------ #

    def cleanup_expired(self, session_max_age_hours: int) -> int:
        cutoff = datetime.datetime.now() - datetime.timedelta(hours=session_max_age_hours)

        with get_connection() as conn:
            cursor = conn.cursor()

            # 若活跃用户的所有 session 都过期，断开连接
            with self._lock:
                if self._active_credential_id is not None:
                    cursor.execute(
                        """
                        SELECT COUNT(*) as cnt FROM sessions
                        WHERE credential_id = ? AND last_active >= ?
                        """,
                        (self._active_credential_id, cutoff),
                    )
                    if cursor.fetchone()["cnt"] == 0:
                        self._disconnect()

            cursor.execute("DELETE FROM sessions WHERE last_active < ?", (cutoff,))
            cursor.execute(
                """
                DELETE FROM credentials
                WHERE id NOT IN (SELECT credential_id FROM sessions)
                """
            )
            conn.commit()
            return cursor.rowcount
