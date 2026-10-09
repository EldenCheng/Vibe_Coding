"""系统信息与依赖自检。

需求里要求「磁盘剩余空间 + 实时速度汇总」，并希望在依赖缺失时给出明确提示
而不是等任务跑失败。这个模块负责把两类信息汇总给前端。
"""
import os
import platform
import shutil
import sys
import time
from pathlib import Path

from . import config as manager_config
from . import fso

# 磁盘剩余空间的告警阈值（低于此值时前端高亮）
DISK_WARN_FREE_GB = 5.0


def _disk_info(path):
    """某个路径所在卷的容量信息。"""
    target = Path(path)
    # 目录可能还不存在，向上找到第一个存在的父目录
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        usage = shutil.disk_usage(str(target))
    except OSError:
        return None
    free_gb = usage.free / (1024 ** 3)
    return {
        "path": str(path),
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "free_gb": round(free_gb, 2),
        "used_percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        "warn": free_gb < DISK_WARN_FREE_GB,
    }


def format_bytes(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.1f} {unit}"
        num /= 1024
    return "-"


def _volume_key(path):
    """把路径归到「卷」上，用于磁盘信息去重。"""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    if os.name == "nt":
        return os.path.splitdrive(str(p))[0].lower() or str(p)
    # POSIX：取挂载点（st_dev 相同即同一卷）
    try:
        return str(p.stat().st_dev)
    except OSError:
        return str(p)


def collect(adapters, task_manager=None):
    """汇总系统信息：平台、解释器、各下载器自检、磁盘剩余、运行中任务与速度。"""
    cfg = manager_config.get_config()
    py, py_src = manager_config.resolve_python(cfg)

    probes = {}
    for type_id, adapter in adapters.items():
        try:
            probes[type_id] = adapter.probe()
        except Exception as exc:
            probes[type_id] = {"type": type_id, "ok": False,
                               "problems": [f"自检异常: {exc}"],
                               "project_dir": str(adapter.project_dir)}
        # 附带输出目录，便于前端展示与排错
        try:
            probes[type_id]["output_root"] = str(adapter.output_root())
        except Exception:
            probes[type_id]["output_root"] = ""

    # 磁盘：对每个下载器的输出目录各查一次（同一卷只保留一条）
    disks = []
    seen = set()
    for type_id, info in probes.items():
        root = info.get("output_root")
        if not root:
            continue
        info_disk = _disk_info(root)
        if not info_disk:
            continue
        key = _volume_key(root)
        if key in seen:
            continue
        seen.add(key)
        info_disk["label"] = adapters[type_id].display_name
        disks.append(info_disk)

    # 运行中任务的实时速度：按产物目录大小做差分估算
    speeds = task_manager.sample_speeds() if task_manager is not None else []

    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "is_windows": os.name == "nt",
            # 后端能否调用本机文件管理器打开目录（供前端决定是否显示按钮）
            "can_open_files": fso.supported(),
            "opener": fso.opener_name() if fso.supported() else "",
        },
        "python": {
            "manager": sys.executable,
            "version": platform.python_version(),
            "worker": py,
            "worker_source": py_src,
        },
        "probes": probes,
        "disks": disks,
        "disk_warn_gb": DISK_WARN_FREE_GB,
        "speeds": speeds,
        "now": time.time(),
    }
