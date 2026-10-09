"""外部已下载文件纳管：把用户用别的工具下好/手工拷进来的剧集并入 批量进度.json。

设计见《Design/项目设计文档.md》§22。场景：用户先用 IDM 下了一部分（文件名与下载器
命名完全不同），重跑 batch 会把已经有了的集**再下一遍**（每集几百 MB）。

做法：扫番剧目录顶层的 *.mp4 → 从文件名猜"第几集" → 与本次解析出的剧集清单**唯一**匹配
→ 写入进度（status=done，file=外部文件名），本轮即跳过。

保守原则（宁可漏，不可错）：
- 文件名猜不出集号 → 不写，只报告；
- 猜出的集号在剧集清单里找不到 / 对应多个条目（多季混排）→ 不写，只报告；
- 进度里已经是 done 的 → 不覆盖（下载器自己的成品优先）；
- 不用文件体积判断"是否下完"：实测低码率的完整文件体积可能只有正常的一半（§22.4）。
"""
import re
from pathlib import Path

# 识别前先剥掉的噪声（画质/编码/来源/字幕标记），避免其中的数字被当成集号
_NOISE_RE = re.compile(
    r"(?i)(?:\d{3,4}[pi](?![a-z0-9])|\d+\s*fps|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|eac3|flac|"
    r"web[-_. ]?dl|webrip|blu-?ray|bdrip|hdrip|hdtv|dvdrip|xvid|divx|"
    r"repack|proper|internal|"
    r"chs|cht|big5|简体|繁体|中字|双语|国语|日语)"
)

# 绝不可能是集号的数字（常见分辨率；四位数年份由"1~3 位"限制天然排除）
_RESOLUTIONS = {144, 240, 360, 480, 540, 576, 720, 1080, 1440, 2160, 4320}

# 高置信模式，按序取第一个命中者
_STRONG_RULES = (
    re.compile(r"第\s*(\d{1,4})\s*[集话話回]"),                    # 第18集 / 第 3 話
    re.compile(r"(?<![A-Za-z0-9])[Ss]\d{1,2}[Ee](\d{1,3})(?![0-9])"),   # S01E05
    re.compile(r"(?<![A-Za-z0-9])\d{1,2}[xX](\d{1,3})(?![0-9])"),        # 2x01
    re.compile(r"(?<![A-Za-z0-9])[Ee][Pp]?[-_.\s]?(\d{1,3})(?![0-9])"),  # E05 / EP05 / Ep.5
    re.compile(r"[\[\(](\d{1,3})[\]\)]"),                                # [05] / (05)
)

# "两边都被分隔符包夹"的数字：能顶住结尾的重复标记（如 IDM 加的 _2）
_BOTH_SIDES_RE = re.compile(r"(?:^|[-_.\s])(\d{1,3})(?=[-_.\s])")
# 放宽版：允许数字就在结尾（含裸数字）—— 兜底用
_LOOSE_RE = re.compile(r"(?:^|[-_.\s])(\d{1,3})(?=[-_.\s]|$)")

# 已知的视频/临时扩展名：只有这些才当扩展名剥掉
# （用 Path.stem 会把 "Show.01" 这类"点+数字"的集名当扩展名吃掉，故手写）
_EXTS = (".mp4", ".mkv", ".avi", ".flv", ".ts", ".m4v", ".mov", ".wmv", ".webm",
         ".rmvb", ".mpg", ".mpeg", ".part", ".tmp", ".crdownload")


def _plausible(num):
    """1~999 且不是常见分辨率，才可能是集号。"""
    return 1 <= num <= 999 and num not in _RESOLUTIONS


def _stem(name):
    """剥掉已知的视频扩展名（不认识的扩展名原样保留）。"""
    text = str(name or "").strip()
    low = text.lower()
    for ext in _EXTS:
        if low.endswith(ext):
            return text[: -len(ext)]
    return text


def episode_number(name):
    """从文件名（或集名）猜集数；猜不出返回 None。

    规则见设计文档 §22.4：先试高置信模式（第N集/S01E05/2x01/E05/[05]），
    再试"两边被分隔符包夹"的数字（**唯一**时才采信——这样
    `牙狼garo-01-…ikanbot.com_2.mp4` 取 1 而不是结尾的 2），最后兜底取最后一个候选。
    """
    text = _stem(name)
    if not text:
        return None
    text = _NOISE_RE.sub(" ", text)

    for rule in _STRONG_RULES:
        for raw in reversed(rule.findall(text)):
            num = int(raw)
            if _plausible(num):
                return num

    both = [int(x) for x in _BOTH_SIDES_RE.findall(text)]
    both = [n for n in both if _plausible(n)]
    if len(set(both)) == 1:
        return both[0]

    loose = [int(x) for x in _LOOSE_RE.findall(text)]
    loose = [n for n in loose if _plausible(n)]
    return loose[-1] if loose else None


def _number_from_url(url):
    """兜底：从 URL 路径里取最后一个数字（与 batch 的集位语义一致）。"""
    try:
        path = re.sub(r"^[a-z]+://[^/]+", "", str(url or ""))
    except Exception:
        return None
    nums = re.findall(r"\d+", path)
    if not nums:
        return None
    num = int(nums[-1])
    return num if _plausible(num) else None


def scan_dir(anime_dir):
    """扫番剧目录**顶层**的 *.mp4 → [(Path, 集号 or None, 字节数)]（按文件名排序）。

    不递归：`_work/`（中间切片）、`image/`（封面）都是目录，天然被排除；
    子目录里的视频在报告里单独提示"已忽略"，避免用户以为扫过了。
    """
    out = []
    root = Path(anime_dir)
    try:
        files = sorted(root.glob("*.mp4"))
    except OSError:
        return out
    for f in files:
        try:
            if not f.is_file():
                continue
            size = f.stat().st_size
        except OSError:
            continue
        out.append((f, episode_number(f.name), size))
    return out


def ignored_subdirs(anime_dir):
    """顶层子目录里的 mp4 数量（用于提示"这些没扫"）。"""
    n = 0
    try:
        for child in Path(anime_dir).iterdir():
            if child.is_dir() and child.name not in ("_work", "image"):
                n += sum(1 for _ in child.rglob("*.mp4"))
    except OSError:
        pass
    return n


def plan_adoption(eps, files, done_urls=()):
    """把扫描结果对应到剧集，给出**可安全写入**的纳管清单。

    eps：本次解析出的剧集（需有 .url / .label）；files：scan_dir() 的返回；
    done_urls：进度里已是完成状态的 URL 集合。
    返回 {"adopt": [...], "already": [...], "unmatched": [...], "ambiguous": [...],
          "empty": [...]}（除 adopt 外都是给用户看的说明文字）。
    """
    by_number = {}
    for ep in eps:
        num = episode_number(getattr(ep, "label", ""))
        if num is None:
            num = _number_from_url(getattr(ep, "url", ""))
        if num is not None:
            by_number.setdefault(num, []).append(ep)

    done = set(done_urls or ())
    adopt, already, unmatched, ambiguous, empty = [], [], [], [], []
    taken = {}          # 集号 → 已采纳的外部文件名（同集多个文件只保第一个）
    for path, num, size in files:
        name = path.name
        if size <= 0:
            empty.append(name)
            continue
        if num is None:
            unmatched.append(name)
            continue
        cands = by_number.get(num) or []
        if not cands:
            unmatched.append(f"{name}（算第 {num} 集，但剧集清单里没有）")
            continue
        if len(cands) > 1:
            ambiguous.append(f"{name}（第 {num} 集对应清单里 {len(cands)} 个条目，无法确定）")
            continue
        ep = cands[0]
        if ep.url in done:
            already.append(f"{name} → {ep.label}")
            continue
        if num in taken:
            ambiguous.append(f"{name}（与 {taken[num]} 都算第 {num} 集，只采纳前者）")
            continue
        taken[num] = name
        adopt.append({"url": ep.url, "label": ep.label, "number": num, "file": name})
    return {"adopt": adopt, "already": already, "unmatched": unmatched,
            "ambiguous": ambiguous, "empty": empty}


def dedupe_by_file(progress, current_urls=()):
    """按成品文件名去重：同一个文件只保留一条记录，返回清理掉的条数。

    站点换线路会让同一集的 m3u8 URL 变化（实测牙狼garo：早先下载走线路5、
    本次解析默认线路1，URL 完全不同），于是进度里同一集会出现多条记录，
    使"完成 X/X 集"的计数虚高。判据严格到**同一个文件名**，不会误删别的集。
    两条冲突时优先保留"出现在本次剧集清单里"的那条，否则保留先写入的那条。
    """
    episodes = progress.data.get("episodes", {})
    current = set(current_urls or ())
    keeper = {}            # 文件名 → 保留的 URL
    dropped = 0
    for url, record in list(episodes.items()):
        name = (record or {}).get("file")
        if not name:
            continue
        keep = keeper.get(name)
        if keep is None:
            keeper[name] = url
            continue
        if url in current and keep not in current:
            episodes.pop(keep, None)
            keeper[name] = url
        else:
            episodes.pop(url, None)
        dropped += 1
    return dropped


def adopt_into(anime_dir, eps, progress, done_urls=None):
    """扫描 + 匹配 + 写进进度，返回报告（供调用方打印）。

    progress 需具备 status(url) / mark_url(...) / save()（即 batch._BatchProgress）。
    """
    files = scan_dir(anime_dir)
    if done_urls is None:
        done_urls = {u for u, v in progress.data.get("episodes", {}).items()
                     if v.get("status") == "done"}
    report = plan_adoption(eps, files, done_urls)
    report["scanned"] = len(files)
    report["ignored_subdir_files"] = ignored_subdirs(anime_dir)
    for item in report["adopt"]:
        progress.mark_url(item["url"], item["label"], "done", file=item["file"], save=False)
    # 纳管之后再按文件名去重：此时"当前线路"的记录已写入，会挤掉换线路前的旧记录
    report["deduped"] = dedupe_by_file(progress, [getattr(e, "url", "") for e in eps])
    if report["adopt"] or report["deduped"]:
        progress.save()
    return report


def format_report(report):
    """把报告渲染成多行日志（中文，逐条列出以便人工核对）。"""
    lines = []
    scanned = report.get("scanned", 0)
    adopted = report.get("adopt", [])
    lines.append(f"[纳管] 扫描番剧目录顶层：{scanned} 个 mp4，"
                 f"其中 {len(adopted)} 个并入批量进度（本轮不再重复下载）")
    for item in adopted:
        lines.append(f"        {item['label']} ← {item['file']}")
    if report.get("already"):
        lines.append(f"[纳管] 已是完成状态，未改动：{len(report['already'])} 个")
    if report.get("deduped"):
        lines.append(f"[纳管] 清理了 {report['deduped']} 条重复记录"
                     f"（同一文件被记在多个线路 URL 下，只保留一条）")
    for key, title in (("ambiguous", "有歧义已跳过"), ("unmatched", "未识别集号已跳过"),
                       ("empty", "0 字节已跳过")):
        items = report.get(key) or []
        if items:
            lines.append(f"[纳管] {title}（{len(items)} 个）:")
            lines.extend(f"        {x}" for x in items)
    if report.get("ignored_subdir_files"):
        lines.append(f"[纳管] 提示：子目录里还有 {report['ignored_subdir_files']} 个 mp4 未扫描"
                     f"（只扫顶层；如需纳管请先移到番剧目录根下）")
    if adopted:
        lines.append("[纳管] 想重新下载某一集：删掉上面列出的那个文件（下次运行会重新下载）")
    return lines
