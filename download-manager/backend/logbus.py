"""任务实时输出的缓冲与广播。

设计要点：
1. 每个任务一条日志流，内存里保留最近 N 行（环形），完整内容追加写入 data/logs/<id>.log。
2. `\r` 与 `\n` 都作为行分隔符：以 `\r` 结束的片段是「原地覆盖当前行」，
   前端据此实现单行进度条刷新，而不是把进度条刷成几百行。
3. 订阅（SSE）用条件变量等待新行，客户端断开时通过 finally 注销，避免长期运行后订阅者泄漏。
"""
import collections
import json
import threading
import time
from pathlib import Path

from . import config as manager_config


class LogLine:
    """一行输出。kind='out' 正常输出，'err' 错误输出，'sys' 管理器自己追加的提示。"""

    __slots__ = ("seq", "ts", "kind", "text", "overwrite")

    def __init__(self, seq, kind, text, overwrite=False):
        self.seq = seq
        self.ts = time.time()
        self.kind = kind
        self.text = text
        self.overwrite = overwrite

    def to_dict(self):
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "text": self.text,
            "overwrite": self.overwrite,
        }


class LogBus:
    """单个任务的输出缓冲。线程安全。"""

    def __init__(self, task_id, mem_lines=2000, log_path=None):
        self.task_id = task_id
        self.mem_lines = mem_lines
        self.log_path = Path(log_path) if log_path else (manager_config.LOG_DIR / f"{task_id}.log")
        self._lines = collections.deque(maxlen=mem_lines)
        self._seq = 0
        self._lock = threading.Condition()
        self._closed = False
        self._fh = None

    # ---- 写入 ----

    def _open_log(self):
        if self._fh is None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = open(self.log_path, "a", encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"[日志] 无法写入 {self.log_path}: {exc}")
                self._fh = False  # False 表示不可用，避免每次重试

    def append(self, kind, text, overwrite=False):
        """追加一行；kind='sys' 用于管理器自己插入的提示行。"""
        with self._lock:
            self._seq += 1
            line = LogLine(self._seq, kind, text, overwrite)
            self._lines.append(line)
            self._write_file(line)
            self._lock.notify_all()
            return line

    def _write_file(self, line):
        self._open_log()
        if self._fh:
            try:
                tag = {"out": "", "err": "[err] ", "sys": "[sys] "}.get(line.kind, "")
                self._fh.write(f"{tag}{line.text}\n")
                self._fh.flush()
            except OSError:
                pass

    def system(self, text):
        """写入一条管理器自己的提示（例如“任务已启动”“进程已退出，退出码 0”）。"""
        return self.append("sys", text)

    # ---- 读取 ----

    def snapshot(self, after_seq=0, tail=None):
        """取日志行。after_seq>0 时只取更新的行；tail 指定只取最后 N 行。"""
        with self._lock:
            lines = list(self._lines)
        if tail is not None:
            lines = lines[-int(tail):]
        elif after_seq:
            lines = [ln for ln in lines if ln.seq > int(after_seq)]
        return [ln.to_dict() for ln in lines]

    def wait_for_lines(self, after_seq, timeout=15.0):
        """阻塞等待 after_seq 之后的新行；超时返回空列表（SSE 心跳用）。"""
        deadline = time.time() + timeout
        with self._lock:
            while not self._closed:
                new = [ln for ln in self._lines if ln.seq > after_seq]
                if new:
                    return [ln.to_dict() for ln in new]
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._lock.wait(remaining)
            # 已关闭：把剩余行吐完
            return [ln.to_dict() for ln in self._lines if ln.seq > after_seq]

    def close(self):
        with self._lock:
            self._closed = True
            self._lock.notify_all()
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    @property
    def last_seq(self):
        with self._lock:
            return self._seq


class LineAssembler:
    """把子进程的字节流切成行，处理 \\r 覆盖与跨块截断。

    用法：assembler.feed(data, kind) → 返回 [(text, overwrite), ...]，
    调用方把它交给 LogBus.append。overwrite=True 表示应覆盖上一行。
    """

    def __init__(self):
        self._buf = ""

    def feed(self, chunk, kind):
        self._buf += chunk
        out = []
        while True:
            # 找到最早的 \n 或 \r
            idx_n = self._buf.find("\n")
            idx_r = self._buf.find("\r")
            candidates = [i for i in (idx_n, idx_r) if i >= 0]
            if not candidates:
                break
            idx = min(candidates)
            text = self._buf[:idx]
            sep = self._buf[idx]
            self._buf = self._buf[idx + 1:]
            # \r\n 视为一个换行
            if sep == "\r" and self._buf.startswith("\n"):
                self._buf = self._buf[1:]
                out.append((text, False))
            elif sep == "\r":
                out.append((text, True))   # 覆盖当前行
            else:
                out.append((text, False))
        return out

    def flush(self):
        """进程结束时把残留的不完整行吐出来。"""
        if self._buf:
            text, self._buf = self._buf, ""
            return [(text, False)]
        return []


class LogRegistry:
    """任务 ID → LogBus 的注册表，供 API 层按任务取日志。"""

    def __init__(self):
        self._buses = {}
        self._lock = threading.Lock()

    def create(self, task_id, mem_lines=None):
        mem = mem_lines or manager_config.get_config()["log"]["mem_lines"]
        with self._lock:
            bus = LogBus(task_id, mem_lines=mem)
            self._buses[task_id] = bus
            return bus

    def get(self, task_id):
        with self._lock:
            return self._buses.get(task_id)

    def drop(self, task_id):
        """从内存注册表移除（日志文件保留）。"""
        with self._lock:
            bus = self._buses.pop(task_id, None)
        if bus:
            bus.close()

    def ids(self):
        with self._lock:
            return list(self._buses)

    def close_all(self):
        for tid in self.ids():
            self.drop(tid)


def cleanup_old_logs(keep_days):
    """删除超过保留天数的日志文件，返回删除数量。"""
    cutoff = time.time() - keep_days * 86400
    removed = 0
    try:
        for f in manager_config.LOG_DIR.glob("*.log"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


def truncate_large_logs(max_mb):
    """把超过大小上限的日志截断成只保留尾部，避免长期运行撑满磁盘。"""
    limit = max_mb * 1024 * 1024
    truncated = 0
    try:
        for f in manager_config.LOG_DIR.glob("*.log"):
            try:
                if f.stat().st_size <= limit:
                    continue
                keep = limit // 2
                with open(f, "rb") as fh:
                    fh.seek(-keep, 2)
                    tail = fh.read()
                with open(f, "w", encoding="utf-8", errors="replace") as fh:
                    fh.write("...(日志超过上限，已截断较早内容)...\n")
                    fh.write(tail.decode("utf-8", errors="replace"))
                truncated += 1
            except OSError:
                pass
    except OSError:
        pass
    return truncated


def sse_pack(event, data):
    """打包一个 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
