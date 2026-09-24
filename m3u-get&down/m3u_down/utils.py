"""通用工具：文件名清洗、URL / Content-Type 判定。"""
import re
from urllib.parse import urlparse

# Windows 文件名非法字符
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_name(name, limit=80):
    """把任意字符串清洗成安全的目录/文件名。"""
    name = _ILLEGAL.sub("_", (name or "").strip()).strip(" .")
    return (name or "video")[:limit]


def is_m3u8_url(url):
    """按路径后缀判定是否为 m3u8 清单地址。"""
    path = urlparse(url).path.lower()
    return path.endswith(".m3u8") or path.endswith(".m3u")


def is_media_segment_url(url):
    """按路径后缀判定是否为媒体切片（TS / fMP4 等）。"""
    path = urlparse(url).path.lower()
    return path.endswith((".ts", ".m4s", ".mp4", ".mpg", ".mpeg", ".aac", ".mp3"))


def looks_like_segment(url, content_type=""):
    """播放器模式用：URL 后缀 + Content-Type 综合判定是否为视频切片。"""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct.startswith("video/"):
        return True
    return is_media_segment_url(url)


def ext_from_url(url, default=".ts"):
    """从 URL 取切片扩展名（含点），取不到用默认值。"""
    path = urlparse(url).path
    tail = path.rsplit("/", 1)[-1]
    if "." in tail:
        return "." + tail.rsplit(".", 1)[-1].lower()
    return default


def format_seconds(s):
    """秒 → mm:ss（超过 1 小时则 h:mm:ss）。"""
    s = max(0, int(s))
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def render_progress(done, total, bytes_done, elapsed, width=24):
    """渲染单行进度条（调用方负责行首 \\r 与 flush）。

    形如：[████████░░░░] 45.2%  162/358 |   96.8MB   6.2MB/s  ETA 00:31
    """
    pct = min(done / total, 1.0) if total else 1.0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    speed = (bytes_done / elapsed) if elapsed > 0 else 0.0
    eta = ((total - done) * elapsed / done) if done and elapsed > 0 else 0.0
    return (f"[{bar}] {pct * 100:5.1f}%  {done}/{total} | "
            f"{bytes_done / 1048576:8.1f}MB  {speed / 1048576:5.1f}MB/s  "
            f"ETA {format_seconds(eta)}")
