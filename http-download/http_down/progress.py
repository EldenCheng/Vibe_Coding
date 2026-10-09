# -*- coding: utf-8 -*-
"""progress.json sidecar 的读写。

位置：<output_dir>/.progress/<安全文件名>.<url-md5前8位>.json
- 原子写（先写 .tmp 再 os.replace），管理器随时来读都不会读到半截
- 管理器的完成判定 / 下载列表状态都依赖这里面的字段，见设计文档 §6
"""
import hashlib
import json
import os
import time
from pathlib import Path


def progress_dir(output_dir):
    return Path(output_dir) / ".progress"


def progress_path(output_dir, filename, url):
    """同一个文件名 + 不同 URL 不会互相覆盖（URL 摘要做后缀）。"""
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    safe = "".join(("_" if c in '<>:"/\\|?*' else c) for c in str(filename)) or "download"
    return progress_dir(output_dir) / f"{safe}.{digest}.json"


def new_state(url, filename, output_dir):
    """一份全新的进度状态（status / bytes_* 字段名与其它下载器风格对齐）。"""
    return {
        "url": url,
        "file": filename,
        "path": str(Path(output_dir) / filename),
        "status": "downloading",
        "bytes_done": 0,
        "bytes_total": 0,
        "mode": "single",
        "segments": [],
        "resumable": False,
        "expected_hash": "",
        "hash_algo": "",
        "actual_sha256": "",
        "error": "",
        "note": "",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": "",
        "finished_at": "",
    }


def write(path, data):
    """原子写入；顺带刷新 updated_at。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read(path):
    """安全读取：任何异常返回 None（文件可能正被写一半或已被清理）。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
