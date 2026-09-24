"""全局配置：内置默认 ← config.json ← CLI 显式参数（优先级递增）。

首次运行会在项目根目录自动生成 config.json（含 _readme 说明键，加载时忽略）。
"""
import json
import shutil
from pathlib import Path

# 项目根目录 = 本包目录的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

_DEFAULTS = {
    "_readme": "concurrency=下载线程数; proxy=代理(http://.. 或 socks5://.., 留空=不启用); "
               "retry_times=单切片重试次数; retry_backoff=重试退避基数(秒); "
               "timeout=读取超时(秒, 连接超时固定15); output_dir=输出根目录; "
               "download_interval=batch每集下载间隔(秒); ffmpeg_path=ffmpeg路径(留空=PATH查找); "
               "insecure=跳过HTTPS证书校验(true/false)",
    "concurrency": 6,
    "proxy": "",
    "retry_times": 3,
    "retry_backoff": 2,
    "timeout": 60,
    "output_dir": "downloads",
    "download_interval": 60,
    "ffmpeg_path": "",
    "insecure": False,
}


def _load():
    """读取 config.json（不存在则生成默认文件），未知键忽略。"""
    data = dict(_DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in _DEFAULTS:
                if k in user:
                    data[k] = user[k]
        except Exception:
            print(f"[配置] {CONFIG_PATH.name} 解析失败，使用默认配置")
    else:
        try:  # 首次运行自动生成，便于用户按需修改
            CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            print(f"[配置] 已生成默认配置文件: {CONFIG_PATH}")
        except Exception:
            pass
    return data


_data = _load()

CONCURRENCY = int(_data["concurrency"])
PROXY = str(_data["proxy"]).strip()
RETRY_TIMES = int(_data["retry_times"])
RETRY_BACKOFF = int(_data["retry_backoff"])
TIMEOUT = (15, int(_data["timeout"]))
OUTPUT_DIR = str(_data["output_dir"])
DOWNLOAD_INTERVAL = int(_data["download_interval"])
FFMPEG_PATH = str(_data["ffmpeg_path"]).strip() or shutil.which("ffmpeg")
INSECURE = bool(_data["insecure"])
