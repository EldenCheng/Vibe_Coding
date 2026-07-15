"""
SMBHandler — 基于 smbprotocol/smbclient 的纯协议实现。
不依赖 net use，每个会话独立管理，天然支持多用户并发。
"""

import io
import os
import stat
import smbclient
import smbclient.path
from smbprotocol.exceptions import SMBException, SMBOSError


class SMBHandler:
    """
    封装对单个共享路径的 SMB 文件操作。
    server / share / credential 在 AuthManager 层注册，
    本类只负责文件 I/O，不管理连接生命周期。
    """

    def __init__(self, server: str, share: str):
        self.server = server
        self.share = share
        # UNC 根路径，例如 \\192.168.8.199\upload
        self.unc_root = f"\\\\{server}\\{share}"

    def _resolve(self, path: str) -> str:
        """将前端传来的相对路径拼接为完整 UNC 路径。"""
        # 统一成反斜杠，去掉首尾多余分隔符
        clean = path.replace("/", "\\").strip("\\")
        if not clean:
            return self.unc_root
        return f"{self.unc_root}\\{clean}"

    # ------------------------------------------------------------------ #
    #  目录列表                                                             #
    # ------------------------------------------------------------------ #

    def list_dir(self, path: str = "/") -> list:
        full_path = self._resolve(path)
        entries = []
        for entry in smbclient.scandir(full_path):
            try:
                info = entry.stat()
                entries.append({
                    "name": entry.name,
                    "is_dir": stat.S_ISDIR(info.st_mode),
                    "size": info.st_size,
                    "mtime": info.st_mtime,
                })
            except (SMBOSError, SMBException):
                entries.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": 0,
                    "mtime": 0,
                })
        return entries

    # ------------------------------------------------------------------ #
    #  新建目录                                                             #
    # ------------------------------------------------------------------ #

    def make_dir(self, path: str) -> None:
        smbclient.makedirs(self._resolve(path), exist_ok=True)

    # ------------------------------------------------------------------ #
    #  上传（从本地临时文件写入 SMB）                                         #
    # ------------------------------------------------------------------ #

    def upload_file(self, local_path: str, remote_path: str) -> None:
        dest = self._resolve(remote_path)
        # 确保父目录存在
        parent = dest.rsplit("\\", 1)[0]
        smbclient.makedirs(parent, exist_ok=True)
        with open(local_path, "rb") as src, smbclient.open_file(dest, mode="wb") as dst:
            dst.write(src.read())

    # ------------------------------------------------------------------ #
    #  下载（从 SMB 写入本地临时文件）                                        #
    # ------------------------------------------------------------------ #

    def download_file(self, remote_path: str, local_path: str) -> None:
        src = self._resolve(remote_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with smbclient.open_file(src, mode="rb") as sf:
            with open(local_path, "wb") as lf:
                lf.write(sf.read())

    # ------------------------------------------------------------------ #
    #  删除                                                                #
    # ------------------------------------------------------------------ #

    def delete(self, path: str, is_dir: bool = False) -> None:
        full_path = self._resolve(path)
        if is_dir:
            smbclient.rmdir(full_path)   # 只删除空目录
        else:
            smbclient.remove(full_path)
