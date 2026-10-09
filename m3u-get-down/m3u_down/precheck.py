"""下载前的"这集要不要重下"判定（v0.10.0，设计见《Design/项目设计文档.md》§24）。

背景：批量按**剧集 URL** 记进度，已完成就跳过；用户想换更高清的版本时，此前只能手动
去目录里删/改名。本模块在下载前读一次 m3u8，用**清单声明值**与现有成品比对，决定跳过
还是重下 —— 不加任何命令行参数。

声明值的可信度（实测 ikanbot/牙狼garo，2026-10-01）：
- 分辨率两头都会错：线路5 声明 `1080x608`、真实 2880×2160；线路6 同样声明 `1080x608`、
  真实只有 640×480；`BANDWIDTH` 也不可信（全声明 800 kbps，实际约 2.4 Mbps）。
- 时长也对不上：清单 `EXTINF` 求和 1475 秒；自家成品 1503 秒；用户 IDM 那批 1456 秒。

所以本模块把声明值当"参考"用，并配三条保险：
① **只升不降**（声明明显更低时跳过，保护已有的 4K 成品）；
② **记忆声明值**（下载时把目标声明值记进进度，之后"声明比声明"，杜绝每次重下/死循环）；
③ **取不到值就不重下**（网络失败、清单结构变化、缺字段一律按跳过处理）。
更准的做法是抓首个切片用 ffprobe 读**真实**分辨率（约 2MB/集），当前按用户决策不采用。
"""
import re

from .parser import load_playlist

# '1080x608' / '1920×1080' 两种写法都要认
_RES_RE = re.compile(r"(\d{1,5})\s*[x×X]\s*(\d{1,5})")

# 判定阈值（集中在此，便于日后按实测调整）
UPGRADE_RATIO = 1.2        # 声明像素数 ≥ 现有 × 1.2 → 认为清单里有更高清版本
DOWNGRADE_RATIO = 0.8      # 声明像素数 ≤ 现有 × 0.8 → 认为清单版本更低（不降级）
DURATION_TOL_RATIO = 0.05  # 时长容差：现有时长的 5%
DURATION_TOL_SEC = 60.0    # 时长容差下限：60 秒（粗检"大块缺失"）


def pixels(resolution):
    """'1080x608' → 656640；解析不出返回 0。"""
    m = _RES_RE.search(str(resolution or ""))
    if not m:
        return 0
    w, h = int(m.group(1)), int(m.group(2))
    return w * h if w and h else 0


def probe(session, url, quality="best", variant_index=None):
    """读清单声明值 → ``{resolution, duration_sec, segments}``；失败返回 ``{}``（绝不抛）。"""
    try:
        pl = load_playlist(session, url, quality=quality,
                           variant_index=variant_index, quiet=True)
    except Exception:
        return {}
    return {
        "resolution": pl.variant_resolution or "",
        "duration_sec": round(pl.declared_duration, 1),
        "segments": len(pl.segments),
    }


def same_declared(record, probed):
    """记录里存的目标声明值与本次是否一致（一致 = 同一份源，直接跳过，防死循环）。"""
    rec = record or {}
    res = rec.get("declared_resolution") or ""
    dur = rec.get("declared_duration")
    if not res or dur in (None, ""):
        return False
    try:
        return (res == (probed.get("resolution") or "")
                and abs(float(dur) - float(probed.get("duration_sec") or 0)) <= 0.5)
    except (TypeError, ValueError):
        return False


def decide(record, probed, line_name=""):
    """判定 → ``(action, reason)``，action ∈ {"skip", "redo"}，reason 为中文说明。

    顺序即优先级：声明记忆 → 线路 → 分辨率（只升不降）→ 时长（粗检）→ 跳过。
    任何一步的值取不到就往下走，最终落到"跳过"——**绝不因为信息缺失而重下**。
    """
    rec = record or {}
    if not probed:
        return "skip", "清单读不到（网络或站点结构变化），按已完成跳过"
    if same_declared(rec, probed):
        return "skip", "清单声明与上次一致（同一份源）"

    # 规则①：记录里写明了来自哪条线路，而本次指定的是另一条
    have_line = (rec.get("line") or "").strip()
    want_line = (line_name or "").strip()
    if have_line and want_line and have_line != want_line:
        return "redo", f"记录线路 {have_line} ≠ 本次 {want_line}"

    # 规则②：分辨率（声明值当参考，只升不降）
    res_target = probed.get("resolution") or ""
    p_target, p_have = pixels(res_target), pixels(rec.get("resolution"))
    if p_target and p_have:
        if p_target >= p_have * UPGRADE_RATIO:
            return "redo", (f"清单声明 {res_target} 高于现有 {rec.get('resolution')}")
        if p_target <= p_have * DOWNGRADE_RATIO:
            return "skip", (f"清单声明 {res_target} 低于现有 {rec.get('resolution')}，不降级")

    # 规则③：时长（粗检，只抓"现有明显缺内容"；声明更短不算问题）
    d_target = float(probed.get("duration_sec") or 0)
    d_have = float(rec.get("duration_sec") or 0)
    if d_target and d_have:
        tol = max(DURATION_TOL_SEC, d_have * DURATION_TOL_RATIO)
        if d_target - d_have > tol:
            return "redo", (f"清单声明 {d_target:.0f} 秒比现有 {d_have:.0f} 秒多 "
                            f"{d_target - d_have:.0f} 秒，疑似缺内容")
    return "skip", "清单声明与现有成品相当"
