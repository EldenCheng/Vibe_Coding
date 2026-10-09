"""适配层公共部分：数据结构与抽象基类。

适配器的职责边界（设计文档 §5）：
- 知道怎么调对应的下载器（拼命令行、定 cwd）
- 知道怎么读它的进度文件、怎么判断完成/部分失败/崩溃
- 知道怎么列出它下载过的产物（供下载列表）
- 知道它的 config.json 有哪些字段（供配置区渲染）
适配器**不**负责进程托管、日志、状态机 —— 那些由 task_manager / runner 统一处理。
"""
import json
import time
from pathlib import Path

# 任务/产物状态的统一取值
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial_failed"      # 跑完了但有失败项
STATUS_FAILED = "failed"
STATUS_CRASHED = "crashed"             # 解释器异常退出
STATUS_STOPPED = "stopped"
STATUS_UNVERIFIED = "completed_unverified"  # 退出码 0 但没有进度文件可核对

STATUS_LABELS = {
    STATUS_RUNNING: "进行中",
    STATUS_COMPLETED: "已完成",
    STATUS_PARTIAL: "部分失败",
    STATUS_FAILED: "已失败",
    STATUS_CRASHED: "异常中断",
    STATUS_STOPPED: "已停止",
    STATUS_UNVERIFIED: "已完成(未核实)",
    "queued": "排队中",
    "interrupted": "服务重启中断",
}


def read_json(path):
    """安全读 JSON：任何异常都返回 None（进度文件可能正被下载器写一半）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def human_size(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return "-"


def dir_size(path, cap_files=20000):
    """递归统计目录大小与文件数。cap_files 用于防止超大目录拖慢扫描。"""
    total = 0
    count = 0
    stack = [Path(path)]
    while stack:
        cur = stack.pop()
        try:
            for entry in cur.iterdir():
                try:
                    if entry.is_dir():
                        stack.append(entry)
                    elif entry.is_file():
                        total += entry.stat().st_size
                        count += 1
                        if count >= cap_files:
                            return total, count
                except OSError:
                    continue
        except OSError:
            continue
    return total, count


def latest_mtime(path):
    """目录下最新的修改时间（用于列表排序）。"""
    newest = 0.0
    try:
        for entry in Path(path).rglob("*"):
            try:
                if entry.is_file():
                    newest = max(newest, entry.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


class DownloadItem:
    """下载列表里的一项（一个画廊 / 一本书 / 一个番剧）。"""

    def __init__(self, item_id, name, path, kind="", progress=None, extra=None):
        self.id = item_id
        self.name = name
        self.path = str(path)
        self.kind = kind
        self.progress = progress or {}
        self.extra = extra or {}

    def to_dict(self):
        size = 0
        files = 0
        mtime = 0.0
        try:
            # 文件型产物（如 http-download 的平铺文件）：dir_size 对文件会返回 0，单独处理
            if Path(self.path).is_file():
                st = Path(self.path).stat()
                size, files, mtime = st.st_size, 1, st.st_mtime
            else:
                size, files = dir_size(self.path)
                mtime = latest_mtime(self.path)
        except OSError:
            pass
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "kind": self.kind,
            "progress": self.progress,
            "extra": self.extra,
            "size": size,
            "size_text": human_size(size),
            "files": files,
            "mtime": mtime,
            "mtime_text": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else "-",
        }


class LaunchPlan:
    """一次任务启动所需的全部信息。"""

    def __init__(self, argv, cwd, kind="download", base_dir=None, target_hint=None, note=""):
        self.argv = argv
        self.cwd = str(cwd)
        self.kind = kind
        self.base_dir = base_dir      # 输出根目录，用于事后定位本次产物
        self.target_hint = target_hint  # 预期目录名（书名/画廊名），仅作兜底
        self.note = note
        self.baseline = {}            # 任务开始时的目录快照（由 task_manager 填充）

    def to_dict(self):
        return {
            "argv": self.argv,
            "cwd": self.cwd,
            "kind": self.kind,
            "base_dir": str(self.base_dir) if self.base_dir else None,
            "target_hint": self.target_hint,
            "note": self.note,
        }


class Adapter:
    """适配器基类。子类必须实现 type_id / display_name / 各 build_* / scan / finalize。"""

    type_id = ""
    display_name = ""
    # 表单里可提交的参数定义（供前端渲染）
    form_schema = []
    # 敏感配置字段（点分路径，支持末尾 .* 通配）
    sensitive_paths = []

    def __init__(self, cfg):
        self.cfg = cfg

    # ---- 基础 ----

    @property
    def project_dir(self):
        from .. import config as manager_config
        return manager_config.project_dir(self.cfg, self.type_id)

    def config_schema(self):
        """返回 [{key,label,type,help,default,options?}]，子类实现。"""
        return []

    def default_output_dir(self):
        """下载器自己 config.json 里的 output_dir；留空则由子类给内置默认。"""
        return ""

    def output_root(self):
        """输出根目录的绝对路径（配置优先，其次下载器项目目录下的默认子目录）。"""
        raw = (self.cfg["projects"].get(self.type_id, {}) or {}).get("output_dir") or ""
        if raw.strip():
            p = Path(raw).expanduser()
            return p if p.is_absolute() else (self.project_dir / p)
        return self.project_dir / (self.default_output_dir() or ".")

    def scan_roots(self):
        """需要扫描哪些目录。默认只有 output_root；子类可加入历史遗留目录。"""
        return [self.output_root()]

    def probe(self):
        """环境自检：项目目录/解释器/关键依赖是否就绪。"""
        from .. import config as manager_config
        ok_dir = self.project_dir.exists()
        py, py_src = manager_config.resolve_python(self.cfg)
        problems = []
        if not ok_dir:
            problems.append(f"项目目录不存在: {self.project_dir}")
        if not py:
            problems.append(py_src)
        return {
            "type": self.type_id,
            "ok": not problems,
            "project_dir": str(self.project_dir),
            "python": py,
            "python_source": py_src,
            "problems": problems,
        }

    # ---- 命令构造 ----

    def build_launch(self, form):
        raise NotImplementedError

    def build_action(self, action, target):
        """按动作名构造命令：check / retry / build_epub / resume 等。"""
        raise NotImplementedError(f"{self.type_id} 不支持动作 {action}")

    def available_actions(self, item=None):
        """该下载器支持哪些列表操作，供前端决定按钮的可用性。"""
        return []

    # ---- 状态 ----

    def locate_target(self, plan, bus=None):
        """任务结束后定位本次的产物目录。

        默认策略（不依赖任务开始时记下的预期目录名，因此服务重启也能用）：
        1. 先看日志里有没有“图片保存在: …”之类的明确路径；
        2. 其次用「任务开始时的目录快照差集」找出本次新建的产物目录。
        """
        return self.detect_target_dir(plan, bus)

    # ---- 目录快照差集（定位本次产物，重启后依然有效） ----

    @staticmethod
    def _list_dirs(root):
        names = set()
        try:
            for child in Path(root).iterdir():
                if child.is_dir() and child.name not in ("__pycache__", "design", "Design"):
                    names.add(child.name)
        except OSError:
            pass
        return names

    def snapshot_dirs(self):
        """记录扫描根目录下现有的子目录名，作为任务前的基线。"""
        snap = {}
        for root in self.scan_roots():
            snap[str(root)] = sorted(self._list_dirs(root))
        return snap

    def find_new_dirs(self, baseline, log_text=""):
        """在基线上找出新出现的产物目录，优先选修改时间最新的一个。"""
        newest, newest_mtime = None, -1.0
        for root in self.scan_roots():
            before = set((baseline or {}).get(str(root), []))
            try:
                children = [c for c in Path(root).iterdir() if c.is_dir()]
            except OSError:
                continue
            for child in children:
                if child.name in before or child.name in ("__pycache__", "design", "Design"):
                    continue
                if not self.is_item_dir(child):
                    continue
                try:
                    pf = child / "progress.json"
                    m = pf.stat().st_mtime if pf.exists() else child.stat().st_mtime
                except OSError:
                    m = 0.0
                if m > newest_mtime:
                    newest, newest_mtime = child, m
        return newest

    def detect_target_dir(self, plan, bus=None):
        """定位本次产物目录，按可靠性依次尝试：

        1. 日志里的明确路径（如“图片保存在: …”）—— 最准；
        2. 目录快照差集 —— 适用于本次新建的产物；
        3. 按身份匹配已有产物 —— 适用于「重跑一个已存在的产物」：
           此时不会有新目录，但进度文件里记着 gid / book_id / URL，可以反查；
        4. 预期目录名 —— 最后兜底。
        """
        if bus is not None:
            found = self.locate_from_log(bus)
            if found is not None:
                return found
        baseline = getattr(plan, "baseline", None) or {}
        if baseline:
            found = self.find_new_dirs(baseline)
            if found is not None:
                return found
        if plan is not None:
            found = self.find_by_identity(plan)
            if found is not None:
                return found
        # 最后兜底：预期目录名（仅当提示存在时）
        hint = getattr(plan, "target_hint", None)
        base = getattr(plan, "base_dir", None)
        if hint and base and (Path(base) / hint).exists():
            return Path(base) / hint
        return None

    def find_by_identity(self, plan):
        """子类可覆盖：按 URL / book_id 在已有产物里反查目标目录。"""
        return None

    def locate_from_log(self, bus):
        """子类可覆盖：从日志文本里解析出产物目录路径。"""
        return None

    @staticmethod
    def is_item_dir(path):
        """子类覆盖：判断某个目录是不是一个下载产物目录。"""
        return True

    def finalize(self, plan, exit_code, log_text=""):
        """按进度文件判断任务结果。返回 {status, message, progress, target_dir}。"""
        raise NotImplementedError

    def scan(self):
        """扫描输出目录，返回 [DownloadItem]。只在用户点刷新时调用。"""
        raise NotImplementedError
