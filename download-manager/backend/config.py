"""管理器自身的配置：读写 download-manager/config.json。

与三个下载器的 config.json 相互独立：
- 本文件配置的是「管理器怎么运行」（端口、令牌、各下载器项目目录、日志策略等）
- 各下载器自己的 config.json 由 config_store.py 负责，那是「下载器怎么工作」
"""
import copy
import json
import secrets
from pathlib import Path

# 项目根目录（download-manager/）
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
TASKS_FILE = DATA_DIR / "tasks.json"
# 单实例锁：防止同时跑两个管理器（它们会互相覆盖 tasks.json，见 instance_lock.py）
LOCK_FILE = DATA_DIR / "server.lock"

# 版本号单一来源：banner 与 /api/health 都读它，改版本只需改这一处（与 版本变更.md 对齐）
VERSION = "0.6.0"

# 默认配置：projects 里的 dir 用相对路径，相对于 download-manager/ 解析，
# 这样四个目录平级放在同一父目录下时，Windows 与 macOS 都不用改配置。
DEFAULTS = {
    "_readme": "统一下载管理器配置。server=监听与访问令牌; python=子进程解释器; "
               "projects=四个下载器的项目目录与输出目录(相对路径相对于 download-manager/); "
               "log=日志策略; notify=通知; sleep_guard=防休眠",
    "server": {
        "host": "0.0.0.0",
        "port": 8765,
        "access_token": "",          # 留空则首次启动自动生成
        "allowed_cidrs": [],         # 空 = 不启用 IP 白名单
    },
    "python": {
        "python_exe": "",            # 留空 = 自动探测
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        },
    },
    "projects": {
        "ebook": {"dir": "../fetech_xs", "output_dir": ""},
        "ehentai": {"dir": "../e-download", "output_dir": ""},
        "video": {"dir": "../m3u-get-down", "output_dir": ""},
        "http": {"dir": "../http-download", "output_dir": ""},
    },
    "log": {
        "max_mb": 20,
        "keep_days": 14,
        "mem_lines": 2000,
    },
    "notify": {
        "desktop": True,
        "sound": False,
    },
    "sleep_guard": {
        "enabled": True,
        "when": "always",            # always = 服务运行期间一直防休眠
    },
}


def _deep_merge(base, override):
    """把 override 递归合并进 base 的副本（dict 逐层合并，其余整体替换）。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    """读取管理器配置：缺失字段用默认值补全，文件不存在则生成一份。

    访问令牌为空时会自动生成一个 32 字节随机串并写回文件，
    这样首次启动就能在控制台打印带令牌的访问地址。
    """
    _ensure_dirs()
    user = {}
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[配置] {CONFIG_PATH.name} 解析失败，改用默认配置: {exc}")
    cfg = _deep_merge(DEFAULTS, user)

    if not cfg["server"].get("access_token"):
        cfg["server"]["access_token"] = secrets.token_urlsafe(24)
        save_config(cfg)
        print("[配置] 已生成新的访问令牌并写入 config.json")
    elif not CONFIG_PATH.exists():
        save_config(cfg)
    return cfg


def save_config(cfg):
    """原子写入配置（写临时文件后替换，避免写一半被读到）。"""
    _ensure_dirs()
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def project_dir(cfg, type_id):
    """把 projects.<type>.dir 解析成绝对路径（相对路径相对于 download-manager/）。"""
    raw = (cfg["projects"].get(type_id, {}) or {}).get("dir") or ""
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


def _interpreter_kind(exe):
    """探测解释器是否为 free-threading（无 GIL）构建。

    返回 (kind, version)：kind 为 "gil" / "free" / None（探测失败）。
    为什么在意：greenlet / Playwright 的**同步 API** 在 Python 3.14t
    （free-threading）上会直接段错误（实测 `sync_playwright().start()` 崩溃），
    而 m3u-get-down 的 sniffer / player_capture / batch 全用同步 API。
    """
    import subprocess
    code = ("import sys;"
            "ok=sys.version_info>=(3,13) and getattr(sys,'_is_gil_enabled',lambda:True)();"
            "print(('gil' if ok else 'free')+' '+sys.version.split()[0])")
    try:
        r = subprocess.run([exe, "-c", code], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            parts = (r.stdout.strip().split() + [""])[:2]
            return parts[0], parts[1]
    except (OSError, subprocess.SubprocessError):
        pass
    return None, ""


def _windows_python_candidates():
    """用 py 启动器列出本机所有 Python（tag, 可执行文件路径）。仅 Windows 有意义。"""
    import re as _re
    import subprocess
    out = []
    try:
        r = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return out
    for line in (r.stdout or "").splitlines():
        m = _re.search(r"-V:(\S+)\s+([A-Za-z]:\\.+?\.exe)", line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def resolve_python(cfg):
    """探测用于运行下载器的 Python 解释器。

    优先级：配置的 python_exe > 管理器自身的解释器 > PATH 里逐个尝试的候选。
    管理器自身的解释器被优先选用，是因为下载器依赖（requests/bs4/lxml 等）
    通常就装在同一个环境里；若下载器跑不起来，可在配置里显式指定 python_exe。

    特例（v0.2.0）：若管理器自己跑在 **free-threading 构建**（Python 3.14t）上，
    而本机同时装有同版本号的普通（GIL）构建，则**自动改用普通构建**运行下载器。
    原因：Playwright 的同步 API 在 free-threading 构建上会段错误，
    而视频下载器的嗅探/批量/播放三种模式都依赖它。
    返回 (可执行文件路径, 来源说明)；找不到时返回 (None, 原因)。
    """
    import shutil
    import sys

    configured = (cfg.get("python", {}) or {}).get("python_exe", "").strip()
    if configured:
        p = Path(configured).expanduser()
        if p.exists():
            return str(p), "配置指定"
        return None, f"配置的 python_exe 不存在: {configured}"

    if sys.executable and Path(sys.executable).exists():
        kind, version = _interpreter_kind(sys.executable)
        if kind == "free":
            for tag, path in _windows_python_candidates():
                if tag.endswith("t") or not Path(path).exists():
                    continue
                alt_kind, alt_version = _interpreter_kind(path)
                if alt_kind == "gil" and alt_version == version:
                    return str(path), (
                        f"自动选用普通(GIL)构建 Python {alt_version}："
                        "管理器同环境是 free-threading 构建，会让 Playwright 崩溃")
        return str(sys.executable), "管理器同环境"

    # Windows 优先 py 启动器（能区分 3.14 与 3.14t），再退 python/python3
    for cand in ("py", "python3", "python"):
        found = shutil.which(cand)
        if found:
            return found, f"PATH 中的 {cand}"
    return None, "未找到可用的 Python 解释器"


# 模块级缓存：启动时读一次即可，后续由 API 显式重载
_cached = None


def get_config(reload=False):
    global _cached
    if _cached is None or reload:
        _cached = load_config()
    return _cached


def update_config(patch):
    """按 patch 合并更新配置并落盘，返回新配置。"""
    global _cached
    merged = _deep_merge(get_config(), patch)
    save_config(merged)
    _cached = merged
    return merged
