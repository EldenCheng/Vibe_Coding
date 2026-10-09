"""任务管理器：队列、状态机、进程托管、完成判定、事件广播。

对应设计文档 §6（状态机与完成判定）与 §13（长期稳定运行）。

核心约束（来自需求 7）：**每种下载器同时只允许一个任务**。
三种下载器之间可以并行，因为它们互不干扰（各自写自己的进度文件）。
同一类型的后续任务进入该类型的 FIFO 队列，而不是被拒绝。
"""
import json
import threading
import time
import uuid
from collections import deque

from . import config as manager_config
from . import runner
from .logbus import LogRegistry, sse_pack
from .adapters.base import STATUS_LABELS, human_size as _format_bytes

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_INTERRUPTED = "interrupted"

# 保留多少条历史任务记录（运行中的永不裁剪）
HISTORY_LIMIT = 200


class Task:
    """一个下载/校验/重下任务。"""

    def __init__(self, type_id, kind, form, argv, cwd, label, log_path, note=""):
        self.id = uuid.uuid4().hex[:12]
        self.type = type_id
        self.kind = kind
        self.form = form or {}
        self.argv = list(argv)
        self.cwd = str(cwd)
        self.label = label
        self.note = note
        self.log_path = str(log_path)
        self.status = STATUS_QUEUED
        self.message = "排队中"
        self.progress = {}
        self.created_at = time.time()
        self.started_at = None
        self.ended_at = None
        self.exit_code = None
        self.pid = None
        self.adopted = False        # 是否是「服务重启后丧失管理的遗留任务」
        self.target_dir = None      # 任务结束后定位到的产物目录
        self.baseline = []          # 任务开始时的目录快照（用于差集定位本次产物）
        self.target_hint = None
        self.base_dir = None
        self.plan = None            # LaunchPlan（服务重启后无法恢复）

    def to_dict(self, queue_position=None):
        return {
            "id": self.id,
            "type": self.type,
            "kind": self.kind,
            "form": self.form,
            "argv": self.argv,
            "cwd": self.cwd,
            "label": self.label,
            "note": self.note,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "message": self.message,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "pid": self.pid,
            "target_dir": self.target_dir,
            "adopted": self.adopted,
            "queue_position": queue_position,
            "log_file": self.log_path,
            "running": self.status == STATUS_RUNNING,
        }

    def brief(self):
        return {
            "id": self.id, "type": self.type, "kind": self.kind, "label": self.label,
            "status": self.status, "status_label": STATUS_LABELS.get(self.status, self.status),
            "message": self.message, "created_at": self.created_at,
        }


class TaskManager:
    """管理所有任务。线程安全。"""

    def __init__(self, cfg, adapters):
        self.cfg = cfg
        self.adapters = adapters
        self.tasks = {}                        # id → Task
        self.queues = {t: deque() for t in adapters}   # 每类型一条队列（存 task id）
        self.running = {}                      # type_id → RunningProcess
        # 每类型一把调度锁：把「检查空位 → 出队 → 启动」串行化，
        # 否则 create_task 与 _on_exit 可能同时看到「无运行中进程」而各启动一个任务，
        # 导致同类型并发跑两个（正是队列要防的）。
        self._pump_locks = {t: threading.Lock() for t in adapters}
        self.logs = LogRegistry()
        self.events = deque(maxlen=300)        # 全局事件（供通知）
        self._speed_samples = {}               # task_id → (时间, 字节数)，用于估算速度
        self._lock = threading.RLock()
        self._event_lock = threading.Condition()
        self._event_seq = 0
        self._stop = threading.Event()
        self._restore_state()

    # ------------------------------------------------------------ 持久化

    def _state_file(self):
        return manager_config.TASKS_FILE

    def _save_state(self):
        """原子写任务记录，供服务重启后回收遗留进程与恢复历史。"""
        with self._lock:
            data = {
                "tasks": [t.to_dict() for t in self.tasks.values()],
            }
            # 只保留最近 HISTORY_LIMIT 条非运行中记录
            if len(data["tasks"]) > HISTORY_LIMIT:
                finished = [t for t in data["tasks"] if t["status"] != STATUS_RUNNING]
                running = [t for t in data["tasks"] if t["status"] == STATUS_RUNNING]
                finished.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
                data["tasks"] = running + finished[:HISTORY_LIMIT - len(running)]
        try:
            path = self._state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            print(f"[任务] 保存任务记录失败: {exc}")

    def _restore_state(self):
        """载入历史任务；对上次遗留的「运行中」任务做强制回收（设计文档 §13.3）。

        理由：服务重启后我们已经失去了那个进程的输出管道，无法再管理它
        （停止按钮会失效、日志收不到）。留着反而危险，因此回收并标记为
        interrupted，界面上提供「续跑」按钮（三个下载器都支持重跑续传）。
        """
        path = self._state_file()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[任务] 读取任务记录失败，忽略: {exc}")
            return

        leftovers = []
        for raw in data.get("tasks", []):
            try:
                task = Task(raw["type"], raw.get("kind", "download"), raw.get("form"),
                            raw.get("argv", []), raw.get("cwd", ""), raw.get("label", ""),
                            raw.get("log_file", ""), raw.get("note", ""))
                task.id = raw.get("id") or task.id
                task.status = raw.get("status", "unknown")
                task.message = raw.get("message", "")
                task.progress = raw.get("progress") or {}
                task.created_at = raw.get("created_at") or task.created_at
                task.started_at = raw.get("started_at")
                task.ended_at = raw.get("ended_at")
                task.exit_code = raw.get("exit_code")
                task.pid = raw.get("pid")
                task.target_dir = raw.get("target_dir")
            except Exception:
                continue
            self.tasks[task.id] = task
            if task.status == STATUS_RUNNING:
                leftovers.append(task)

        for task in leftovers:
            alive = runner.process_alive(task.pid) if task.pid else False
            if alive:
                ok, detail = runner.kill_tree(task.pid)
                task.message = f"服务重启，已强制回收遗留进程（PID {task.pid}）: {detail}"
            else:
                task.message = "服务重启，之前运行的进程已结束"
            task.adopted = True
            task.status = STATUS_INTERRUPTED
            task.ended_at = task.ended_at or time.time()
            bus = self.logs.create(task.id)
            bus.system(f"[恢复] {task.message}")
            bus.system("[恢复] 该任务已脱离管理，可点「续跑」重新发起（会自动跳过已完成部分）")
            bus.close()
            print(f"[任务] {task.id} {task.message}")

        if leftovers:
            self._save_state()

    # ------------------------------------------------------------ 事件广播

    def _emit(self, event, payload):
        """记录并广播一个全局事件（前端据此弹通知）。"""
        with self._event_lock:
            self._event_seq += 1
            item = {"seq": self._event_seq, "ts": time.time(), "event": event, "data": payload}
            self.events.append(item)
            self._event_lock.notify_all()
        return item

    def wait_events(self, after_seq, timeout=15.0):
        """SSE 用：等待 after_seq 之后的新事件。"""
        deadline = time.time() + timeout
        with self._event_lock:
            while not self._stop.is_set():
                new = [e for e in self.events if e["seq"] > after_seq]
                if new:
                    return new
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._event_lock.wait(remaining)
        return []

    def events_since(self, after_seq):
        with self._event_lock:
            return [e for e in self.events if e["seq"] > after_seq]

    # ------------------------------------------------------------ 查询

    def get(self, task_id):
        with self._lock:
            return self.tasks.get(task_id)

    def list_tasks(self, type_id=None, limit=None):
        with self._lock:
            items = list(self.tasks.values())
            if type_id:
                items = [t for t in items if t.type == type_id]
            items.sort(key=lambda t: t.created_at, reverse=True)
            out = []
            for t in items:
                pos = None
                if t.status == STATUS_QUEUED:
                    q = self.queues.get(t.type, ())
                    if t.id in q:
                        pos = list(q).index(t.id) + 1
                out.append(t.to_dict(queue_position=pos))
            return out[:limit] if limit else out

    def active_count(self):
        with self._lock:
            return sum(1 for t in self.tasks.values()
                       if t.status in (STATUS_RUNNING, STATUS_QUEUED))

    def is_busy(self, type_id):
        with self._lock:
            if type_id in self.running:
                proc = self.running[type_id]
                if proc.is_running():
                    return True
            return bool(self.queues.get(type_id))

    # ------------------------------------------------------------ 创建任务

    def create_task(self, type_id, kind, form):
        """创建并（在有空位时）启动任务。返回 Task。"""
        adapter = self.adapters.get(type_id)
        if adapter is None:
            raise ValueError(f"未知的下载器类型: {type_id}")

        if kind == "download":
            plan = adapter.build_launch(form)
            label = self._label_for(adapter, form, plan)
        else:
            plan = adapter.build_action(kind, form.get("target") or {})
            label = f"{adapter.display_name} · {kind}"

        py, py_src = manager_config.resolve_python(self.cfg)
        if not py:
            raise ValueError(f"找不到可用的 Python 解释器：{py_src}")

        task = Task(type_id, kind, form, plan.argv, plan.cwd, label,
                    log_path=manager_config.LOG_DIR / f"pending.log", note=plan.note)
        task.log_path = str(manager_config.LOG_DIR / f"{task.id}.log")
        task.target_hint = getattr(plan, "target_hint", None)
        task.base_dir = getattr(plan, "base_dir", None)
        task.plan = plan
        # 任务前拍目录快照：任务结束后用差集定位本次新建的产物目录。
        # 不依赖「任务开始时先知道输出目录名」，所以服务重启后依然能定位。
        try:
            plan.baseline = adapter.snapshot_dirs()
            task.baseline = plan.baseline
        except Exception as exc:
            print(f"[任务] 记录目录快照失败（不影响运行）: {exc}")

        with self._lock:
            self.tasks[task.id] = task
            self.queues.setdefault(type_id, deque()).append(task.id)
        self.logs.create(task.id)
        bus = self.logs.get(task.id)
        if bus:
            bus.system(f"[任务] {label}")
            if plan.note:
                bus.system(f"[说明] {plan.note}")
            if plan.target_hint:
                bus.system(f"[预期目录] {plan.target_hint}")
        self._emit("task_created", task.brief())
        self._save_state()
        self._pump(type_id)
        return task

    def _label_for(self, adapter, form, plan):
        """给任务起个人类可读的名字。"""
        if adapter.type_id == "ehentai":
            url = (form.get("url") or "").strip()
            return f"E-Hentai · {url.rsplit('/', 2)[-2] if url.endswith('/') else url[-12:]}"
        if adapter.type_id == "ebook":
            return f"电子书 · {form.get('book')}"
        if adapter.type_id == "video":
            mode = form.get("mode", "get")
            return f"视频({mode}) · {(form.get('url') or '')[-40:]}"
        if adapter.type_id == "http":
            url = (form.get("url") or "").strip()
            return f"直链 · {(url.rsplit('/', 1)[-1] or url)[:40]}"
        return adapter.display_name

    # ------------------------------------------------------------ 调度

    def _pump(self, type_id):
        """该类型空闲且队列非空时启动下一个任务（同类型严格串行）。"""
        lock = self._pump_locks.setdefault(type_id, threading.Lock())
        with lock:
            while True:
                with self._lock:
                    proc = self.running.get(type_id)
                    if proc is not None and proc.is_running():
                        return
                    queue = self.queues.setdefault(type_id, deque())
                    if not queue:
                        return
                    task_id = queue.popleft()
                    task = self.tasks.get(task_id)
                if task is None:
                    continue
                # 启动成功即结束（_start 已在内部把进程登记到 running）
                if self._start(task):
                    return
                # 启动失败：继续尝试队列里的下一个，直到队空或成功

    def _start(self, task):
        """启动一个任务。成功返回 True，失败返回 False（供 _pump 继续尝试）。"""
        adapter = self.adapters.get(task.type)
        env = runner.build_env((self.cfg.get("python", {}) or {}).get("env") or {})
        bus = self.logs.get(task.id) or self.logs.create(task.id)

        task.status = STATUS_RUNNING
        task.started_at = time.time()
        task.message = "运行中"
        self._emit("task_started", task.brief())

        def on_exit(proc, code):
            self._on_exit(task, proc, code)

        try:
            proc = runner.RunningProcess(task.id, task.argv, task.cwd, env, bus, on_exit)
            proc.start()
        except (OSError, ValueError) as exc:
            bus.system(f"[错误] 启动失败: {exc}")
            task.status = "failed"
            task.message = f"启动失败: {exc}"
            task.ended_at = time.time()
            self._emit("task_failed", task.brief())
            self._save_state()
            return False

        with self._lock:
            self.running[task.type] = proc
        task.pid = proc.pid
        self._save_state()
        return True

    def _on_exit(self, task, proc, exit_code):
        """进程退出：判定结果、广播、继续跑队列。"""
        bus = self.logs.get(task.id)
        adapter = self.adapters.get(task.type)
        task.exit_code = exit_code
        task.ended_at = time.time()

        # 读完整日志用于判定（fetech_xs 崩溃与大日志都靠它）
        log_text = ""
        try:
            with open(task.log_path, encoding="utf-8", errors="replace") as fh:
                log_text = fh.read()[-200000:]
        except OSError:
            pass

        if proc.stop_requested:
            task.status = "stopped"
            task.message = "已被手动停止（重新运行可继续）"
        else:
            try:
                outcome = adapter.finalize(task.plan, exit_code, log_text) if adapter else {}
            except Exception as exc:
                outcome = {"status": "failed", "message": f"结果判定出错: {exc}", "progress": {}}
            task.status = outcome.get("status", "failed")
            task.message = outcome.get("message", "")
            task.progress = outcome.get("progress") or {}
            if outcome.get("target_dir"):
                task.target_dir = outcome["target_dir"]

        if task.status == "completed":
            task.progress = {**task.progress, "percent": 100}
        if bus:
            bus.system(f"[进程] 已退出，退出码 {exit_code}")
            bus.system(f"[结果] {STATUS_LABELS.get(task.status, task.status)}：{task.message}")

        with self._lock:
            if self.running.get(task.type) is proc:
                self.running.pop(task.type, None)
        self._emit("task_finished", {**task.brief(), "exit_code": exit_code,
                                     "progress": task.progress})
        self._save_state()
        self._pump(task.type)

    # ------------------------------------------------------------ 停止 / 移除

    def stop(self, task_id):
        task = self.get(task_id)
        if task is None:
            raise ValueError("任务不存在")
        with self._lock:
            if task.status == STATUS_QUEUED:
                q = self.queues.get(task.type)
                if q and task_id in q:
                    q.remove(task_id)
                task.status = "stopped"
                task.message = "已从队列移除"
                task.ended_at = time.time()
                self._save_state()
                return task
            proc = self.running.get(task.type)
        if task.status != STATUS_RUNNING or proc is None or proc.task_id != task.id:
            raise ValueError("任务当前不在运行，无需停止")
        threading.Thread(target=proc.stop, daemon=True).start()
        task.message = "正在停止..."
        return task

    def remove(self, task_id):
        task = self.get(task_id)
        if task is None:
            raise ValueError("任务不存在")
        if task.status == STATUS_RUNNING:
            raise ValueError("任务正在运行，请先停止再移除")
        with self._lock:
            self.tasks.pop(task_id, None)
            q = self.queues.get(task.type)
            if q and task_id in q:
                q.remove(task_id)
        self.logs.drop(task_id)
        self._save_state()
        return task

    # ------------------------------------------------------------ 速度采样

    def sample_speeds(self):
        """估算运行中任务的实时速度。

        做法：定期统计任务产物目录的总字节数，用两次采样的差值算速度。
        比解析日志里的进度条更通用 —— 三个下载器的输出格式互不相同，
        但「产物在变大」是共同事实。目录可能很大，这里限制遍历文件数。
        """
        now = time.time()
        results = []
        # 先在锁内取快照，再在锁外做目录遍历：目录统计可能很慢（大产物），
        # 不能在持锁期间进行，否则会阻塞任务调度与状态更新。
        with self._lock:
            running_types = [t for t, p in self.running.items()
                             if p is not None and p.is_running()]
            tasks = [t for t in self.tasks.values() if t.status == STATUS_RUNNING]

        for task in tasks:
            target = task.target_dir
            # 还没定位到产物目录时，用快照差集试着找；找不到就用输出根目录
            if not target:
                adapter = self.adapters.get(task.type)
                if adapter is not None:
                    try:
                        found = adapter.find_new_dirs(getattr(task, "baseline", None))
                        if found:
                            target = str(found)
                    except Exception:
                        pass
            if not target:
                adapter = self.adapters.get(task.type)
                target = str(adapter.output_root()) if adapter else None
            if not target:
                continue

            from .adapters.base import dir_size
            size, _ = dir_size(target, cap_files=5000)
            prev = self._speed_samples.get(task.id)
            speed = None
            if prev and now > prev[0]:
                delta = size - prev[1]
                elapsed = now - prev[0]
                if delta >= 0 and elapsed > 0:
                    speed = delta / elapsed
            self._speed_samples[task.id] = (now, size)

            results.append({
                "task_id": task.id,
                "type": task.type,
                "label": task.label,
                "status": task.status,
                "size": size,
                "size_text": _format_bytes(size),
                "speed": speed,
                "speed_text": (f"{_format_bytes(speed)}/s" if speed else "计算中"),
                "target": target,
            })
        return results

    # ------------------------------------------------------------ 生命周期

    def start_housekeeping(self):
        """后台线程：定期清理过期日志、压缩超大日志、落盘任务记录。"""

        def loop():
            while not self._stop.wait(600):
                try:
                    cfg = manager_config.get_config()
                    log_cfg = cfg.get("log", {})
                    from .logbus import cleanup_old_logs, truncate_large_logs
                    removed = cleanup_old_logs(int(log_cfg.get("keep_days", 14)))
                    truncated = truncate_large_logs(int(log_cfg.get("max_mb", 20)))
                    if removed or truncated:
                        print(f"[日志] 清理 {removed} 个过期日志，截断 {truncated} 个超大日志")
                    self._save_state()
                except Exception as exc:
                    print(f"[日志] 清理线程出错: {exc}")

        threading.Thread(target=loop, daemon=True, name="housekeeping").start()

    def shutdown(self):
        """服务退出：不主动杀任务（前台运行时 Ctrl+C 由用户决定）。"""
        self._stop.set()
        with self._event_lock:
            self._event_lock.notify_all()
        self._save_state()


class _plan_stub:
    """把 Task 伪装成 LaunchPlan，供 adapter.finalize 复用同一套判定逻辑。

    定位本次产物目录不依赖 target_hint（服务重启后它会丢失），
    而是用任务开始时拍下的目录快照做差集，见 Task.detect_target_dir。
    """

    def __init__(self, task):
        self.kind = task.kind
        self.base_dir = getattr(task, "base_dir", None)
        self.target_hint = getattr(task, "target_hint", None)
        self.argv = task.argv
        self.cwd = task.cwd
