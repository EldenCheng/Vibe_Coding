"""已下载视频的简要信息（分辨率 / 时长）：ffprobe 读成品，供进度与 简介.md 记录。

设计见《Design/项目设计文档.md》§23：
- 统一从**成品文件**读，不用 m3u8 里声明的 RESOLUTION —— 声明与实际编码未必一致，
  而且外部纳管进来的文件根本没有清单可读（那种情况只能靠探测文件本身）
- 只探测"缺信息"的文件，结果写回 批量进度.json，后续运行直接复用（0 成本）
- 探测失败（无 ffprobe / 文件损坏 / 超时）只留空，**绝不影响下载与状态判定**

线路**不在本模块**：它只能由下载器在下载时记录；外部文件的来源无从得知，猜就是错。
"""
import json
import subprocess
from pathlib import Path

from .merger import find_ffprobe


def format_duration(seconds):
    """秒 → '25:06'；超过 1 小时 → '1:25:06'；无效/非正值返回空串。"""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def probe(path):
    """ffprobe 读成品 → {'resolution': '640×480', 'duration_sec': 1512.3}；失败返回 {}。

    只取第一条视频流的宽高与容器的时长（合并后的 mp4 这两个值最可信）。
    """
    exe = find_ffprobe()
    path = Path(path)
    if not exe or not path.exists():
        return {}
    try:
        r = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=120)
        info = json.loads(r.stdout or "{}")
    except Exception:
        return {}                      # 探测失败不抛错：这只是"锦上添花"的信息
    out = {}
    stream = (info.get("streams") or [{}])[0]
    width, height = stream.get("width"), stream.get("height")
    try:
        if width and height:
            out["resolution"] = f"{int(width)}×{int(height)}"
    except (TypeError, ValueError):
        pass
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
        if duration > 0:
            out["duration_sec"] = round(duration, 1)
    except (TypeError, ValueError):
        pass
    return out


def fill_progress(progress, anime_dir):
    """给进度里"已完成但缺分辨率/时长"的记录补录，返回补录条数。

    只探测文件确实存在的记录（外部纳管的文件也算）；探测不到就保持缺省，下次运行再试。
    这样"第一次运行补齐、之后 0 成本"，也不会因为探测失败而影响任何状态判定。
    """
    episodes = progress.data.get("episodes", {})
    targets = []
    for url, record in episodes.items():
        name = (record or {}).get("file")
        if not name or (record.get("resolution") and record.get("duration_sec")):
            continue
        if (Path(anime_dir) / name).exists():
            targets.append((url, name))
    if not targets:
        return 0
    print(f"[媒体信息] 读取 {len(targets)} 个成品文件的分辨率/时长 ...")
    filled = 0
    for url, name in targets:
        info = probe(Path(anime_dir) / name)
        if info:
            episodes[url].update(info)
            filled += 1
    if filled:
        progress.save()
        print(f"[媒体信息] 已补录 {filled}/{len(targets)} 个"
              f"（写入 批量进度.json，下次不再重复探测）")
    else:
        print("[媒体信息] 本次未能读到信息（缺 ffprobe 或文件损坏），跳过")
    return filled
