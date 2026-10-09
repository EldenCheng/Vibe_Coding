"""ffmpeg concat 合并：切片 → 完整 mp4，ffprobe 成品完整性校验。"""
import json
import shutil
import subprocess
from pathlib import Path

from . import config


def find_ffmpeg():
    """定位 ffmpeg：config 优先，其次 PATH。"""
    return config.FFMPEG_PATH or shutil.which("ffmpeg")


def find_ffprobe():
    """定位 ffprobe：优先与 ffmpeg 同目录（ffmpeg_path 指向非 PATH 位置时），其次 PATH。"""
    ff = find_ffmpeg()
    if ff:
        sibling = Path(ff).with_name("ffprobe" + (".exe" if ff.lower().endswith(".exe") else ""))
        if sibling.exists():
            return str(sibling)
    return shutil.which("ffprobe")


def check_output(path):
    """ffprobe 校验成品可播放：时长 > 0 且含视频流（无音频流仅告警）。

    找不到 ffprobe 时跳过校验（打印提示，不视为失败）。
    """
    probe = find_ffprobe()
    if not probe:
        print("[校验] 未找到 ffprobe，跳过成品完整性校验")
        return
    r = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True)
    try:
        info = json.loads(r.stdout or "{}")
    except Exception:
        info = {}
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    types = [s.get("codec_type") for s in info.get("streams") or []]
    if r.returncode != 0 or duration <= 0 or "video" not in types:
        raise RuntimeError(f"成品校验未通过（duration={duration}, streams={types}）"
                           "——切片可能不完整或损坏，重跑同一命令可续传重试")
    if "audio" not in types:
        print("[校验] 警告：成品不含音频流")
    print(f"[校验] 成品完整性通过（时长 {duration:.0f} 秒）")


def merge(out_dir, seg_dir, seg_files, output_name="output.mp4", init_fname=None):
    """按切片序号顺序无损合并（-c copy）。

    seg_files: {序号: 文件名}；init_fname: fMP4 初始化段（排在 concat 首位）。
    只合并从 0 号起无缺号的连续前缀，保证产出是可播放的完整段。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请安装后加入 PATH（https://ffmpeg.org）")

    files = []
    if init_fname and (seg_dir / init_fname).exists():
        files.append(init_fname)
    i = 0
    while i in seg_files and (seg_dir / seg_files[i]).exists():
        files.append(seg_files[i])
        i += 1
    if not files:
        raise RuntimeError("没有可合并的切片")
    if not init_fname and seg_files and i != max(seg_files) + 1:
        print(f"[合并] 警告：切片存在缺口，只合并前 {i} 个（0~{i - 1}）")

    out_dir = Path(out_dir)
    # concat demuxer 用相对路径 + 正斜杠，避免平台差异
    list_path = out_dir / "filelist.txt"
    lines = [f"file '{(seg_dir / f).relative_to(out_dir).as_posix()}'" for f in files]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_path = out_dir / output_name
    base_cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                # 注意：进程以 out_dir 为工作目录执行，输入/输出必须用绝对路径，
                # 否则相对路径会在 cwd 下二次拼接导致找不到文件
                "-i", str(list_path.resolve()),
                "-c", "copy", "-avoid_negative_ts", "make_zero"]
    # TS 源的 AAC 常需要 aac_adtstoasc 位流过滤：先裸合，失败再带过滤重试
    r = subprocess.run(base_cmd + [str(out_path.resolve())], cwd=str(out_dir),
                       capture_output=True, text=True)
    if r.returncode != 0:
        r2 = subprocess.run(base_cmd + ["-bsf:a", "aac_adtstoasc",
                                        str(out_path.resolve())],
                            cwd=str(out_dir), capture_output=True, text=True)
        if r2.returncode != 0:
            err = (r2.stderr or r.stderr or "").strip()[-2000:]
            raise RuntimeError(f"ffmpeg 合并失败：\n{err}")
    return out_path
