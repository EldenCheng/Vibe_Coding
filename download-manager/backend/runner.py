"""子进程托管：启动下载器、回收输出、终止整棵进程树。

零第三方依赖（不依赖 psutil），自己按平台实现进程树终止。

关键点（对应设计文档 §8 与 §13）：
- 用 `python -u` + PYTHONIOENCODING=utf-8 启动，否则看不到实时输出且中文会崩。
- 两个线程分别读 stdout / stderr，用 errors="replace" 解码，绝不因编码问题中断。
- 停止任务时必须杀「整棵进程树」：Playwright 浏览器、ffmpeg 都是下载器的子进程，
  只杀父进程会留下孤儿进程继续占网络与磁盘。
  · Windows：taskkill /PID <pid> /T /F（/T 连带子树）
  · POSIX(macOS/Linux)：子进程用 start_new_session 建独立进程组，killpg 整组终止
"""
import os
import subprocess
import threading
import time
from pathlib import Path

from .logbus import LineAssembler


class RunningProcess:
    """一个正在运行的下载器进程。"""

    def __init__(self, task_id, argv, cwd, env, bus, on_exit):
        self.task_id = task_id
        self.argv = argv
        self.cwd = str(cwd)
        self.env = env
        self.bus = bus
        self.on_exit = on_exit
        self.proc = None
        self.pid = None
        self.returncode = None
        self.started_at = time.time()
        self.stop_requested = False
        self._readers = []
        self._exit_handled = False
        self._lock = threading.Lock()
        # 子孙进程看护（见 v0.2.0）：进程自然退出后，下载器可能留下孤立的
        # 浏览器 / ffmpeg 子进程。父进程一死，系统会把它们重新挂到别的父进程上，
        # 之后就再也通过 pid 找不到它们了。因此必须在进程存活期间就定期记录子孙，
        # 退出后按记录逐个回收。
        self._known_children = set()
        self._pgid = None

    # ---- 生命周期 ----

    def start(self):
        """启动进程并开始读取输出。"""
        creationflags = 0
        popen_kwargs = {}
        if os.name == "nt":
            # 新进程组：配合 taskkill /T 收干净整棵子树
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            # 独立会话 = 新进程组，killpg 可用
            popen_kwargs["start_new_session"] = True

        self.bus.system(f"$ {' '.join(self.argv)}")
        self.bus.system(f"[工作目录] {self.cwd}")
        self.proc = subprocess.Popen(
            self.argv,
            cwd=self.cwd,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            **popen_kwargs,
        )
        self.pid = self.proc.pid
        self.bus.system(f"[进程] PID {self.pid} 已启动")

        # 记住进程组（POSIX 下用于整组回收）并启动子进程看护线程
        if os.name != "nt":
            try:
                self._pgid = os.getpgid(self.pid)
            except OSError:
                self._pgid = None
        else:
            threading.Thread(target=self._watch_children, daemon=True).start()

        self._readers = [
            threading.Thread(target=self._pump, args=(self.proc.stdout, "out"), daemon=True),
            threading.Thread(target=self._pump, args=(self.proc.stderr, "err"), daemon=True),
        ]
        for t in self._readers:
            t.start()

        threading.Thread(target=self._wait, daemon=True).start()
        return self

    def _pump(self, stream, kind):
        """读取一路管道，按行（含 \\r）推给日志总线。

        **必须用 read1 而不是 read**：Popen 默认（bufsize=-1）给的是 BufferedReader，
        而 BufferedReader.read(n) 会一直阻塞到**凑满 n 字节或 EOF** 才返回。
        下载器那种「每 1~2 秒打印一行」的输出远小于 n，于是会攒够 4KB 才一次性喷出来 ——
        用户看到的现象就是「文件夹里在下载，但输出区一直没动静，
        直到某一刻突然刷出几百行」。实测对比（子进程每秒一行、共 6 行）：

            read(4096)  → 6.03s 才收到 48 字节（等于等到进程退出）
            read1(4096) → 每行 0.03/1.03/2.03s... 即时收到

        read1 有多少返回多少，半行由 LineAssembler 负责拼接。
        """
        assembler = LineAssembler()
        reader = getattr(stream, "read1", None) or stream.read
        try:
            while True:
                chunk = reader(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                for line, overwrite in assembler.feed(text, kind):
                    self.bus.append(kind, line, overwrite=overwrite)
        except (OSError, ValueError):
            pass
        finally:
            for line, overwrite in assembler.flush():
                self.bus.append(kind, line, overwrite=overwrite)
            try:
                stream.close()
            except OSError:
                pass

    def _wait(self):
        """等进程退出，收干输出、回收残留子孙后再回调（保证判定时日志完整）。"""
        code = self.proc.wait()
        for t in self._readers:
            t.join(timeout=5)
        self.returncode = code
        # 回收下载器可能留下的孤儿子进程（浏览器 / ffmpeg 等），
        # 必须在启动下一个任务之前完成，否则长期运行会越积越多。
        self.reap_children()
        with self._lock:
            if self._exit_handled:
                return
            self._exit_handled = True
        try:
            self.on_exit(self, code)
        except Exception as exc:  # 回调异常不能影响进程回收线程
            self.bus.system(f"[错误] 任务收尾失败: {exc}")

    # ---- 子孙进程看护与回收（v0.2.0） ----

    def _watch_children(self):
        """Windows：进程存活期间每 2 秒记录一次全部子孙 PID。

        父进程退出后再找子孙是找不到的（会被系统重新挂到别的父进程），
        所以只能在存活期间先记下来。
        """
        while self.proc is not None and self.proc.poll() is None:
            try:
                self._known_children |= _win_descendants(self.pid)
            except Exception:
                pass
            time.sleep(2)

    def reap_children(self):
        """回收仍存活的子孙进程。返回回收数量（-1 表示清理了整个进程组）。

        - Windows：按看护线程记录的 PID 逐个 TerminateProcess（记录里只有子孙，
          不含自己，所以不必关心顺序）。
        - POSIX：子进程已建独立进程组，直接 killpg SIGKILL 剩余的组员。
        """
        if self.stop_requested:
            return 0  # 主动停止时 stop() 已负责回收，避免重复
        killed = 0
        if os.name == "nt":
            # 退出前再补一次快照，尽量不漏
            try:
                self._known_children |= _win_descendants(self.pid)
            except Exception:
                pass
            for child in list(self._known_children):
                if child == self.pid or not process_alive(child):
                    continue
                ok, _ = _win_terminate(child)
                if ok:
                    killed += 1
        elif self._pgid:
            import signal
            try:
                os.killpg(self._pgid, signal.SIGKILL)
                killed = -1
            except (ProcessLookupError, OSError):
                pass
        if killed > 0:
            self.bus.system(f"[清理] 已回收 {killed} 个残留子进程")
        elif killed < 0:
            self.bus.system("[清理] 已清理残留的进程组")
        return killed

    # ---- 终止 ----

    def stop(self, timeout=10):
        """终止整棵进程树：先温和终止，超时后强杀。"""
        self.stop_requested = True
        if self.proc is None or self.proc.poll() is not None:
            return
        self.bus.system("[停止] 正在终止任务及其子进程（浏览器/ffmpeg 等）...")
        if os.name == "nt":
            ok, detail = _kill_tree_windows(self.pid)
            if not ok:
                self.bus.system(f"[停止] 进程树终止未完全成功：{detail}")
                self._kill_direct()
            return
        self._stop_posix(timeout)

    def _stop_posix(self, timeout):
        import signal
        try:
            pgid = os.getpgid(self.pid)
        except OSError:
            self._kill_direct()
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except OSError:
            self._kill_direct()
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return
            time.sleep(0.2)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            self._kill_direct()

    def _kill_direct(self):
        try:
            self.proc.kill()
        except OSError:
            pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None


def _win_process_table():
    """枚举当前所有进程，返回 {pid: ppid}。

    用 CreateToolhelp32Snapshot 而不是 tasklist：taskkill/tasklist 在部分受限环境下
    会被拒绝（Access denied），而快照 API 与 TerminateProcess 仍然可用。
    """
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE or not snapshot:
        return {}
    table = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return {}
        while True:
            table[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def _win_descendants(pid):
    """返回指定 PID 的全部子孙 PID 集合（不含自己）。

    用于在进程存活期间记录子进程，供退出后回收（见 RunningProcess.reap_children）。
    """
    pid = int(pid)
    table = _win_process_table()
    if not table or pid not in table:
        return set()
    children = {}
    for child_pid, parent_pid in table.items():
        children.setdefault(parent_pid, []).append(child_pid)
    result = set()
    stack = list(children.get(pid, []))
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def _win_terminate(pid):
    """用 TerminateProcess 结束单个进程。返回 (是否成功, 说明)。"""
    import ctypes
    PROCESS_TERMINATE = 0x0001
    ERROR_ACCESS_DENIED = 5
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return False, f"OpenProcess 失败(err={kernel32.GetLastError()})"
    try:
        if kernel32.TerminateProcess(handle, 1):
            return True, "TerminateProcess 成功"
        err = kernel32.GetLastError()
        return False, ("进程已不存在" if err == 1168  # ERROR_NOT_FOUND
                       else f"TerminateProcess 失败(err={err})")
    finally:
        kernel32.CloseHandle(handle)


def _kill_tree_windows(pid):
    """终止 Windows 上的整棵进程树。返回 (是否成功, 说明)。

    顺序很关键：先杀子孙再杀父进程，否则父进程一死，
    剩下的子进程会被系统重新挂到别的父进程上，就找不到了。
    """
    table = _win_process_table()
    if not table:
        # 拿不到进程表时退回 taskkill
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, check=False, timeout=20)
            return r.returncode == 0, f"taskkill 返回 {r.returncode}"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"taskkill 执行失败: {exc}"

    # 建立 父 → 子 关系，收集整棵树
    children = {}
    for child_pid, parent_pid in table.items():
        children.setdefault(parent_pid, []).append(child_pid)

    order = []
    stack = [int(pid)]
    seen = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        order.append(current)
        stack.extend(children.get(current, []))

    failures = []
    # 反向遍历 = 先叶子后根
    for target in reversed(order):
        ok, detail = _win_terminate(target)
        if not ok and target == int(pid):
            failures.append(f"PID {target}: {detail}")
    return not failures, "; ".join(failures) or f"已终止 {len(order)} 个进程"


def kill_tree(pid, timeout=8):
    """强制回收一棵进程树（服务重启时回收遗留进程用）。

    返回 (是否成功, 说明文本)。进程已不存在也算成功。
    """
    if not pid:
        return True, "无 PID"
    if os.name == "nt":
        return _kill_tree_windows(pid)

    import signal
    try:
        pgid = os.getpgid(int(pid))
        os.killpg(pgid, signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(int(pid), 0)
            except OSError:
                return True, "已终止"
            time.sleep(0.2)
        os.killpg(pgid, signal.SIGKILL)
        return True, "已强制终止"
    except ProcessLookupError:
        return True, "进程已不存在"
    except OSError as exc:
        return False, f"终止失败: {exc}"


def _alive_windows(pid):
    """Windows 下判断 PID 是否存活。

    优先用 Win32 API（OpenProcess），它比 tasklist 更快也更可靠：
    tasklist 在某些受限环境下不可用（返回码 1、无输出），那时会误判为「已结束」。
    """
    pid = int(pid)
    # 1) Win32 API：能打开句柄就说明进程存在
    try:
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            try:
                code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    # 259 = STILL_ACTIVE（仍在运行，也可能是尚未取退出码的僵尸）
                    return code.value == STILL_ACTIVE
                return True
            finally:
                kernel32.CloseHandle(handle)
        # 打开失败：区分「不存在」与「无权限」
        ERROR_INVALID_PARAMETER = 87
        ERROR_ACCESS_DENIED = 5
        err = kernel32.GetLastError()
        if err == ERROR_INVALID_PARAMETER:
            return False
        if err == ERROR_ACCESS_DENIED:
            return True
    except Exception:
        pass

    # 2) 退回 tasklist（注意：受限环境可能不可用）
    try:
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                capture_output=True, text=True, check=False, timeout=10)
        return str(pid) in (result.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def process_alive(pid):
    """判断 PID 是否仍然存活（服务重启时识别遗留任务用）。"""
    if not pid:
        return False
    if os.name == "nt":
        return _alive_windows(pid)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # 存在但无权限，视为存活
    except (OSError, ValueError):
        return False


def build_env(extra_env=None):
    """构造子进程环境：注入 UTF-8 与无缓冲，并去掉可能干扰的变量。"""
    env = os.environ.copy()
    env.update(extra_env or {})
    # 让下载器的中文与 ✓/✗ 不会在 Windows 控制台编码下崩掉
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # 某些终端下会干扰 Playwright 的渲染输出
    env.pop("PYTHONSTARTUP", None)
    return env


def detect_ffmpeg(cfg=None):
    """探测 ffmpeg 是否可用（视频下载器合并切片必需）。"""
    import shutil
    return shutil.which("ffmpeg")


def detect_playwright(python_exe):
    """探测指定解释器里有没有 playwright（m3u 的顶层依赖，缺了连 get 都不能用）。"""
    if not python_exe:
        return False, "未找到 Python 解释器"
    try:
        r = subprocess.run([python_exe, "-c", "import playwright"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, "已安装"
        return False, "未安装（py -m pip install playwright 并 py -m playwright install chromium）"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"探测失败: {exc}"


def detect_module(python_exe, module):
    """探测指定解释器里有没有某个模块，返回 (是否存在, 说明)。"""
    if not python_exe:
        return False, "未找到 Python 解释器"
    try:
        r = subprocess.run([python_exe, "-c", f"import {module}"],
                           capture_output=True, text=True, timeout=30)
        return (r.returncode == 0, "已安装" if r.returncode == 0 else "未安装")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"探测失败: {exc}"
