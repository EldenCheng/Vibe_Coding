"""单实例锁：保证同一时间只有一个管理器实例在跑。

为什么需要它（而不是只靠端口检查）：

1. **状态文件会互相覆盖**：每个实例都维护自己的内存任务表，却共享同一份
   `data/tasks.json`；`_save_state()` 只写自己知道的那份，谁后存盘谁就把对方的记录抹掉。
   实测事故：两个实例同时监听 8765，后启动的那个存盘后，一个正在下载的任务记录凭空消失，
   界面上连「续跑」按钮都没了。
2. **端口检查不足以拦截**：Windows 上 `SO_REUSEADDR` 允许重复绑定一个正在被监听的端口
   （见 `server.py:check_port` 与设计文档 §20.12），而且用户完全可能用 `--port 9000`
   手动再起一个——端口不同，但状态文件还是那一份。

做法：`data/server.lock` 里记录 `{pid, host, port, started_at, python}`。
- 锁存在且记录的 PID 仍存活 → 拒绝启动，并打印占用者信息；
- 记录的 PID 已不存在 → 视为陈旧锁（上次崩溃/断电留下的），直接接管；
- `--force` 可跳过检查（供测试与特殊场景使用）。

已知局限：只按 PID 判存活，理论上存在「PID 被系统复用」的极小概率误判，
这时用 `--force` 或删掉锁文件即可。
"""
import json
import os
import time
from pathlib import Path

from . import config as manager_config
from . import runner


class InstanceLock:
    """data/server.lock 的读写与存活判断。"""

    def __init__(self, path=None):
        self.path = Path(path) if path else manager_config.LOCK_FILE
        self.info = None          # 自己写入的锁内容
        self._held = False

    # ---- 读 ----

    def read(self):
        """读锁文件；不存在或损坏都返回 None。"""
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def holder_alive(self, data):
        """锁里记录的进程是否还活着。"""
        pid = (data or {}).get("pid")
        if not pid:
            return False
        try:
            return runner.process_alive(int(pid))
        except (TypeError, ValueError):
            return False

    # ---- 写 ----

    def acquire(self, host, port, force=False):
        """尝试取得锁。

        返回 (是否成功, 说明)。失败时说明里带占用者的 PID/端口/启动时间，
        便于用户判断该去关哪个窗口（或删锁文件）。

        `force=True`：**既不检查也不占锁**。这样测试脚本（如 recovery_test
        会故意另起一个服务实例）既不会拦到自己，也不会把真实实例的锁覆盖掉。
        """
        if force:
            return True, "已跳过单实例检查（--force，未写入锁文件）"

        existing = self.read()
        if existing and self.holder_alive(existing):
            started = existing.get("started_at")
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)) if started else "未知"
            who = (f"PID {existing.get('pid')}"
                   f"（{existing.get('host')}:{existing.get('port')}，启动于 {when}）")
            return False, f"已有一个管理器在运行：{who}"

        if existing:
            # 陈旧锁：上次进程没来得及清理（崩溃、拔电、被强杀）
            self._write(host, port)
            return True, f"接管了陈旧锁（原记录 PID {existing.get('pid')} 已不存在）"

        self._write(host, port)
        return True, ""

    def _write(self, host, port):
        import sys
        self.info = {
            "pid": os.getpid(),
            "host": host,
            "port": int(port),
            "started_at": time.time(),
            "python": sys.executable,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.info, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            self._held = True
        except OSError as exc:
            # 锁写不下去不该拦住服务启动（例如目录只读），但要让用户知道
            print(f"[警告] 无法写入单实例锁 {self.path}: {exc}")
            self._held = False

    def release(self):
        """释放锁。只删自己写的那份，避免误删后来者的锁。"""
        if not self._held or not self.info:
            return
        current = self.read()
        if current and current.get("pid") not in (None, self.info.get("pid")):
            return
        try:
            self.path.unlink()
        except OSError:
            pass
        self._held = False
