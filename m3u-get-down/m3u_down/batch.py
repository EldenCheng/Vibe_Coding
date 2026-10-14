"""列表页批量下载：解析剧集清单 → 生成简介.md → 逐集嗅探下载。

设计见《Design/项目设计文档.md》§10.3：
- 列表页两级解析（requests 正则优先，Playwright DOM 兜底）
- 模板分组取最大组 + 列表页 ID 过滤 + 去重 + 自然排序
- 每集独立工作目录（集间隔离，避免续传数据串台），成品扁平移动为 番剧名/集名.mp4
- 批量进度.json 记录状态，已完成集跳过（中断续跑），单集失败不阻塞
- 已完成集下载前会用清单声明值判一次"要不要重下"（v0.10.0，见 precheck.py / §24）
"""
import html as _html
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from . import config, cover, embedded, external, mediainfo, precheck, sites
from .downloader import run as run_download
from .parser import load_playlist
from .session import DEFAULT_UA, build_session, session_from_sniff
from .sniffer import sniff as run_sniff
from .utils import is_m3u8_url, sanitize_name

_LINK_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Episode:
    label: str   # 集名（链接文本或从 URL 推断）
    url: str     # 播放页地址（内嵌播放器站点则为 m3u8 直链）
    alts: list = None   # 备选线路播放页列表（主 URL 失败时按序 failover）
    line: int = None    # 线路序号（1 基；内嵌播放器站点用于展示/标注）
    line_name: str = ""  # 线路名（内嵌站点才有，如 "线路5 (dyttm3u8)"），下载后记进进度


# ---------- 列表页解析 ----------

def _fetch_html(url, direct_first=False):
    """requests 拉取页面文本，中文站无 charset 声明时用内容探测兜底。

    走 build_session 统一会话：配置了代理时页面抓取也按站点出口偏好走
    （与下载出口一致），连接层失败自动切另一出口。
    """
    session = build_session(direct_first=direct_first)
    r = session.get(url, timeout=config.TIMEOUT)
    r.raise_for_status()
    if (r.encoding or "").lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or r.encoding
    return r.text, r.url


def _render_html(url, direct_first=False):
    """Playwright 兜底：JS 渲染的列表页在浏览器里展开后取 DOM。"""
    from playwright.sync_api import sync_playwright
    from .sniffer import context_kwargs, launch_browser
    with sync_playwright() as p:
        browser = launch_browser(p)
        context = browser.new_context(**context_kwargs(probe_url=url,
                                                       direct_first=direct_first))
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)   # 留给 JS 渲染列表
            html_text = page.content()
        finally:
            browser.close()
    return html_text, url


def _meta_content(html_text, names):
    """提取 meta 标签 content（兼容 property/name 前置或后置两种顺序）。"""
    for name in names:
        esc = re.escape(name)
        for pat in ('<meta[^>]+(?:property|name)=["\']' + esc +
                    '["\'][^>]*content=["\']([^"\']*)["\']',
                    '<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']'
                    + esc + '["\']'):
            m = re.search(pat, html_text, re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
    return ""


def _deep_unescape(s):
    """迭代 HTML 实体解码：部分站点是双重转义（&amp;quot;），单次解码不够。"""
    for _ in range(3):
        if not re.search(r"&[a-zA-Z#0-9]+;", s or ""):
            break
        s = _html.unescape(s)
    return s


def _extract_info(html_text, site=None):
    """提取番剧标题 / 剧情简介 / 封面图 URL（site 提供简介清洗规则）。

    v0.7.2：站点 detail 规则优先（title/cover/description 为保留键，其余为附加键），
    规则不中时逐字段回退下方原有通用提取，行为与旧版一致。"""
    detail = site.extract_detail(html_text) if site is not None else {}
    title = detail.pop("title", "")
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    title = _deep_unescape(_TAG_RE.sub("", m.group(1))).strip() if m and not title else title
    if not title:
        m = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
        if m:
            title = m.group(1).strip()
            # 去掉"在线观看/高清视频"及站点后缀等噪声
            title = re.split(r"在线观看|高清|全集", title)[0].split("-")[0].strip("《》 -，,")
    desc = detail.pop("description", "") or _meta_content(html_text, ("description", "og:description"))
    desc = _deep_unescape(desc or "")
    if site is not None:
        desc = site.clean_desc(desc)
    elif "|" in desc:   # 通用兜底：去掉站点拼接的"剧情摘要 | 站点名"后缀
        desc = desc.split("|")[0].strip()
    # 局部变量名避开模块名 cover（同名只是作用域内遮蔽，容易看错；统一叫 cover_url）
    cover_url = detail.pop("cover", "") or _meta_content(html_text, ("og:image",))
    if cover_url:
        # 容错：修复部分站点把域名和图片 URL 直接拼接的畸形地址
        i = cover_url.rfind("http")
        if i > 0:
            cover_url = cover_url[i:]
    return title, {"description": _deep_unescape(desc or ""),
                   "cover": cover_url or "", **detail}


def _label_from_url(url):
    """链接无文本时从路径数字推断集名，如 /p/202678-1-1/ → 第1-1集。"""
    nums = re.findall(r"\d+", urlparse(url).path)
    if len(nums) >= 2:
        return f"第{int(nums[-2])}-{int(nums[-1])}集"
    if len(nums) == 1:
        return f"第{int(nums[0])}集"
    tail = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return tail or "未命名"


def _extract_episodes(html_text, base, list_url, site=None):
    """从 HTML 收集剧集链接：模板分组/站点正则 + ID 过滤 + 集位去重 + 自然排序。

    站点配置（site）提供精修规则：play_pattern 直解析、线路偏好策略、集名清洗；
    未提供时按通用引擎（v0.2.0 行为）。每个集位保留按偏好排序的备选线路 alts。
    """
    host = urlparse(list_url).netloc
    links = []
    for m in _LINK_RE.finditer(html_text):
        href = _html.unescape(m.group(1).strip())
        if href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        full = urljoin(base, href)
        if urlparse(full).netloc != host:
            continue
        text = _html.unescape(_TAG_RE.sub("", m.group(2)))
        text = re.sub(r"\s+", " ", text).strip()
        links.append((full, text))

    def _nums(u):
        return re.findall(r"\d+", urlparse(u).path)

    # 1a) 站点配置了 play_pattern：直接正则解析出 (线路号, 集位)
    if site is not None and site.play_pattern is not None:
        items = []
        for u, t in links:
            parts = site.extract_parts(u)
            if parts:
                items.append((u, t, parts[1], parts[2]))
        # ID 过滤：播放 URL 的 id 组必须出现在列表页路径数字里
        list_tokens = set(_nums(list_url))
        if list_tokens and items:
            items = [(u, t, line, pos) for u, t, line, pos in items
                     if (site.extract_parts(u) or ("",))[0] in list_tokens]
    else:
        # 1b) 通用引擎：按"路径数字→{d}"的模板分组，剧集页必然是站内最大同模板群
        groups = {}
        for u, t in links:
            tpl = re.sub(r"\d+", "{d}", urlparse(u).path)
            groups.setdefault(tpl, []).append((u, t))
        if not groups:
            return []
        _, picked = max(groups.items(), key=lambda kv: len(kv[1]))
        # 2) 只保留路径含列表页 ID 数字 token 的链接（剔除同模板的其他番剧）
        list_tokens = set(_nums(list_url))
        if list_tokens:
            picked = [(u, t) for u, t in picked
                      if set(_nums(u)) & list_tokens]
        # (线路号, 集位)：路径倒数第二段/末段数字
        items = []
        for u, t in picked:
            nums = _nums(u)
            line = int(nums[-2]) if len(nums) >= 2 else 0
            pos = nums[-1] if nums else u
            items.append((u, t, line, pos))
    if not items:
        return []

    # 3) 去重与选线：同 URL 去重；同"集位"多线路去重——聚合站的列表页常为
    #    每条线路重复一份完整集表。选线策略由站点配置决定：
    #    - line_asc（默认）：线路号小者优先（站点默认源），其次带集数文本者，再按页面序
    #    - complete_first：先给每条线路打分（集名序号与集位一致的条数、集表条数），
    #      集"完整且自洽"的线路优先——容错某条线路集表残缺/错位的站点
    #    主 URL 之外的线路按同样顺序留作 alts（failover 换线重试用）
    #    局限：同页混多季且集名完全相同时只保留先出现的季，多季番剧请用各季列表页。
    def _is_ep_text(t):
        return bool(re.search(r"第\s*\d+\s*[集話话]|EP?\s*\d+", t, re.I))

    def _label_digits(t):
        t = site.clean_label(t) if site is not None else t
        m = re.search(r"\d+", t)
        return int(m.group()) if m else None

    line_stat = {}   # 线路号 → (集表条数, 集名序号与集位一致的条数)
    for u, t, line, pos in items:
        c, ok = line_stat.get(line, (0, 0))
        line_stat[line] = (c + 1, ok + (1 if _label_digits(t) == int(pos) else 0))

    def _rank(idx, u, t, line, pos):
        if site is not None and site.line_preference == "complete_first":
            c, ok = line_stat.get(line, (0, 0))
            return (-ok, -c, line, idx)
        return (line, 0 if _is_ep_text(t) else 1, idx)

    seen_url, ordered = set(), []
    for idx, (u, t, line, pos) in enumerate(items):
        if u not in seen_url:
            seen_url.add(u)
            ordered.append((idx, u, t, line, pos))
    failover_max = site.failover_max if site is not None else 3
    eps = []
    for pos, cands in sorted(((p, c) for p, c in _group_pos(ordered, _rank).items()),
                             key=lambda kv: _pos_key(kv[0])):
        cands.sort(key=lambda x: x[0])
        main_u, main_t = cands[0][2], cands[0][3]
        alts = [u for _, _, u, _, _, _ in cands[1:failover_max]]
        label = ""
        if _is_ep_text(main_t):
            label = main_t
        else:   # 主候选无集数文本（如"立即播放"按钮）→ 取该集位任一带集数文本者
            for _, _, _, t, _, _ in cands:
                if _is_ep_text(t):
                    label = t
                    break
        label = site.clean_label(label) if site is not None else label
        eps.append(Episode(label=label or main_t or _label_from_url(main_u),
                           url=main_u, alts=alts))

    # 4) 自然排序（数字按数值比较，第2集不会排到第10集后面）
    eps.sort(key=lambda e: [int(x) if x.isdigit() else x.lower()
                            for x in re.split(r"(\d+)", e.label + " " + e.url)])
    return eps


def _group_pos(ordered, rank):
    """按集位聚合候选（保持页序），元素为 (排序键, idx, url, 文本, 线路, 集位)。"""
    by_pos = {}
    for idx, u, t, line, pos in ordered:
        by_pos.setdefault(pos, []).append(
            (rank(idx, u, t, line, pos), idx, u, t, line, pos))
    return by_pos


def _pos_key(pos):
    """集位排序键：纯数字按数值，其余按字符串。"""
    return (0, int(pos), "") if str(pos).isdigit() else (1, 0, str(pos))


def parse_list_page(list_url, site=None):
    """解析列表页，返回 (标题, meta{description,cover,list_url}, [Episode])。

    site 为站点精修配置；传 None 时按域名自动匹配，匹配不到走通用引擎。
    """
    if site is None:
        site = sites.match(list_url)
    df = bool(site and site.proxy_policy == "direct_first")
    html_text, base = _fetch_html(list_url, direct_first=df)
    title, meta = _extract_info(html_text, site)
    eps = _extract_episodes(html_text, base, list_url, site)
    if not eps:
        print("[批量] requests 未解析到剧集链接，尝试浏览器渲染兜底 ...")
        html_text, base = _render_html(list_url, direct_first=df)
        title, meta = _extract_info(html_text, site)
        eps = _extract_episodes(html_text, base, list_url, site)
    meta["list_url"] = list_url
    return title, meta, eps


# ---------- 简介页 ----------

def _write_info(path, title, meta, eps, status_by_url, selected_urls, records=None):
    """生成/回写 简介.md（状态随下载进度更新，直接整文件重写）。

    封面（v0.7.3）：本地已落盘时引用 image/cover.* 相对路径（远程图床会先于视频失效）；
    本地化失败时只留一行文字提示，不显示远程链接（宁缺毋滥，避免裂图）。
    视频信息（v0.9.0）：新增「下载线路 / 分辨率 / 时长」三列，取自 records
    （即 批量进度.json 的 episodes），未知一律填 —。
    """
    records = records or {}

    def _rec(url):
        return records.get(url) or {}

    lines = [f"# {title}", ""]
    if meta.get("cover_local"):
        lines += [f"![封面]({meta['cover_local']})", ""]
    elif "cover_local" in meta and meta.get("cover"):
        # 已尝试本地化但没成功（或图床失效）：只留文字提示，不显示远程链接（避免裂图）
        lines += ["> 封面图未能保存到本地，此处不再显示（原图链接可能已失效）。", ""]
    elif meta.get("cover"):     # 未走本地化流程的旧调用方：保持原行为
        lines += [f"![封面]({meta['cover']})", ""]
    lines += [f"> 来源列表页：{meta.get('list_url', '')}", ""]
    extras = [(k, v) for k, v in meta.items()
              if k not in ("description", "cover", "cover_local", "list_url") and v]
    if extras:   # 站点 detail 配置的附加信息（v0.7.2），键名即显示标签
        lines += ["## 视频信息", ""]
        lines += [f"- {k}：{v}" for k, v in extras]
        lines += [""]
    if meta.get("description"):
        lines += ["## 剧情简介", "", meta["description"], ""]
    lines += ["## 剧集清单", "", "| # | 集名 | 链接 | 状态 | 下载线路 | 分辨率 | 时长 |",
              "|---|------|------|------|----------|--------|------|"]
    for i, ep in enumerate(eps, 1):
        if status_by_url.get(ep.url) == "done":
            st = "完成"
        elif status_by_url.get(ep.url) == "failed":
            st = "失败"
        elif ep.url in selected_urls:
            st = "待下载"
        else:
            st = "未选择"
        link = f"直链·线路{ep.line}" if ep.line else f"<{ep.url}>"
        rec = _rec(ep.url)
        row_line = rec.get("line") or "—"
        row_res = rec.get("resolution") or "—"
        row_dur = mediainfo.format_duration(rec.get("duration_sec")) or "—"
        lines.append(f"| {i} | {ep.label} | {link} | {st} | "
                     f"{row_line} | {row_res} | {row_dur} |")
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ---------- 选集 ----------

def _parse_spec(spec, n):
    """解析 '1-12,15' 形式的集数范围（1 基），返回 0 基下标列表。"""
    idx = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            if not (1 <= a <= b <= n):
                raise RuntimeError(f"集数范围 {part} 超出 1~{n}")
            idx.update(range(a - 1, b))
        else:
            k = int(part)
            if not (1 <= k <= n):
                raise RuntimeError(f"集数 {part} 超出 1~{n}")
            idx.add(k - 1)
    return sorted(idx)


def _select(eps, spec=None, yes=False):
    """展示清单并选集：回车全下 / 范围表达式 / q 退出。返回 0 基下标或 None。"""
    n = len(eps)
    print(f"\n[批量] 共解析到 {n} 集：")
    for i, ep in enumerate(eps, 1):
        show = f"直链·线路{ep.line}" if ep.line else ep.url
        print(f"  {i:>3}. {ep.label}   {show}")
    if spec:
        # 显式范围优先于 --yes（脚本化指定集数时不能被"全下"覆盖）
        return _parse_spec(spec, n)
    if yes:
        return list(range(n))
    raw = input("回车全部下载 / 输入范围如 1-12,15 / q 退出: ").strip()
    if raw.lower() in ("q", "quit", "exit"):
        return None
    return list(range(n)) if not raw else _parse_spec(raw, n)


# ---------- 内嵌播放器（mvffm 式：直链写在页面 JS，无需嗅探） ----------

def _ep_label(name):
    """剧集名格式化：'1'/'01' → '第01集'；非数字名原样保留。"""
    name = str(name or "").strip()
    if name.isdigit():
        return f"第{int(name):02d}集"
    return name or "未命名"


def _build_embedded_episodes(video_urls, line_idx, site, line_name=""):
    """按选中线路构建 Episode：主 URL = 该线路各集 m3u8，alts = 同集其他线路。"""
    failover_max = site.failover_max if site is not None else 3
    line = video_urls[line_idx] if line_idx < len(video_urls) else []
    others = [l for i, l in enumerate(video_urls) if i != line_idx]
    eps = []
    for pos, entry in enumerate(line):
        url = str(entry.get("url") or "")
        if not url:
            continue
        alts = [l[pos]["url"] for l in others
                if pos < len(l) and (l[pos].get("url") or "")]
        eps.append(Episode(label=_ep_label(entry.get("name")), url=url,
                           alts=alts[:max(0, failover_max - 1)],
                           line=line_idx + 1, line_name=line_name))
    return eps


def _probe_alive(video_urls, make_session):
    """按序探测各线路第一集直链，返回第一条存活线路的下标（0 基）。

    聚合站死链常见（实测 ikanbot 9 条线路 4 条失效），固定默认第 1 条会
    让每集都先撞死链再 failover，白付超时代价。判定：GET 首集直链，
    状态 200 且响应以 #EXTM3U 开头即存活。全部失效返回 None（调用方
    回退第 1 条，交给既有 failover）。

    每条线路用新会话探测（make_session 工厂）：死链导致的出口降级只影响
    该次探测，不会因会话粘性污染后续线路的出口选择。
    """
    dead = []
    for i, line in enumerate(video_urls):
        url = next((str(e.get("url")) for e in line if e.get("url")), None)
        if not url:
            continue
        try:
            r = make_session().get(url, timeout=(5, 10))
            alive = r.status_code == 200 and "#EXTM3U" in (r.text or "")[:64]
        except Exception:
            alive = False
        if alive:
            if dead:
                print(f"[批量] 默认线路探活: 线路{', 线路'.join(dead)} 失效，"
                      f"改用线路{i + 1}")
            return i
        dead.append(str(i + 1))
    if dead:
        print(f"[批量] 默认线路探活: 全部线路失效（线路{', 线路'.join(dead)}），"
              f"回退线路 1 由 failover 逐集重试")
    return None


def _parse_embedded_page(list_url, site, line, insecure=None, proxy=None):
    """内嵌播放器站点：解析直链、列出线路、按选中线路构建剧集清单。

    返回 (标题, meta, [Episode])。线路选择：未指定 --line 时探活取
    第一条存活线路（聚合站死链常见）；--line（序号或名字）匹配不到时
    提示并回退探活结果。
    """
    html_text, base = _fetch_html(
        list_url, direct_first=site.proxy_policy == "direct_first")
    df = site.proxy_policy == "direct_first"

    def make_session():
        """解析 API 与各线路探活共用同一套参数（referer/代理/出口偏好）。"""
        return build_session(referer=list_url, insecure=insecure, proxy=proxy,
                             direct_first=df)

    # 解析器可能需要发请求（如 ikanbot_api），用与下载一致的 session
    session = make_session()
    line_names, video_urls = embedded.parse(html_text, site.player_embedded,
                                            session=session, page_url=base)
    if not video_urls:
        raise RuntimeError("未从页面解析到内嵌播放器直链（站点结构可能已变化）")
    print(f"[批量] 内嵌播放器直链: {len(video_urls)} 条线路")
    idx = embedded.line_match(line_names, line)
    if line is not None and idx is None:
        print(f"[批量] --line 未匹配到线路: {line!r}，改为探活选默认线路")
    if idx is None:
        idx = _probe_alive(video_urls, make_session)
    if idx is None:
        idx = 0
    for i, name in enumerate(line_names, 1):
        print(f"  [{i}] {name}" + (" ← 默认" if i == idx + 1 else ""))
    if line is not None and idx is not None:
        print(f"[批量] 已选择线路: [{idx + 1}] {line_names[idx]}")
    title, meta = _extract_info(html_text, site)
    meta["list_url"] = list_url
    eps = _build_embedded_episodes(video_urls, idx, site,
                                   line_names[idx] if idx < len(line_names) else "")
    return title, meta, eps


# ---------- 批量进度 ----------

class _BatchProgress:
    """批量进度.json：按剧集 URL 记录状态，重跑自动跳过已完成。

    v0.11.0 新增两个**顶层**键（不属于 episodes 内任何一集）：
    - ``list_url``：本目录对应的原始入口地址（列表页，或裸 m3u8 直链）。
      管理器「续跑」按钮靠它重新发起 batch 命令——此前管理器拿不到地址，
      只能报"缺少地址，无法续跑"。
    - ``resume_hint``：续跑时要带回的 ``--line`` / ``--pick``。
      不带的后果：内嵌站点重新探活可能换到另一条线路，触发 v0.10 判定
      "线路变化→重下"，把整个番剧的已完成集全部重下一遍。
    """

    def __init__(self, path, list_url=""):
        self.path = Path(path)
        self.data = {"episodes": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.data.setdefault("episodes", {})
        # 每次运行都用本次任务的入口 URL 刷新：同一目录只会来自同一个入口
        # （用户手工把 A 番剧简介复制到 B 目录的极端情况，以最后一次运行为准）
        if list_url:
            self.data["list_url"] = list_url

    def set_resume_hint(self, line=None, pick=None):
        """记录续跑要带回的 --line/--pick（仅在有变化时落盘）。

        yt-dlp 路径 line 恒为空（不适用），pick 默认 1；管理器据此
        只在 hint 与命令行默认值不同时才补参数，避免多余参数带来噪音提示。
        """
        hint = {"line": str(line) if line else "",
                "pick": int(pick) if pick else 1}
        if self.data.get("resume_hint") != hint:
            self.data["resume_hint"] = hint
            self.save()

    def status(self, url):
        return self.data["episodes"].get(url, {}).get("status")

    def file_of(self, url):
        """进度里记录的成品文件名（外部纳管的文件与下载器命名不同，靠它定位）。"""
        return (self.data["episodes"].get(url) or {}).get("file") or ""

    def status_map(self):
        """{剧集URL: 状态}，供简介页状态表使用。"""
        return {u: v.get("status") for u, v in self.data.get("episodes", {}).items()}

    def done_urls(self):
        """已是完成状态的 URL 集合（纳管时用于"不覆盖既有记录"）。"""
        return {u for u, v in self.data.get("episodes", {}).items()
                if v.get("status") == "done"}

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def mark_url(self, url, label, status, file="", save=True, **extra):
        """写一条进度记录；extra 只保留有值的键（line/resolution/duration_sec 等）。

        在已有记录上**合并**而不是替换：这样可以保留此前记下的 line / resolution /
        duration_sec（例如"先失败、后被纳管补记为完成"时不会把已知信息抹掉）。
        """
        record = dict(self.data["episodes"].get(url) or {})
        record.update({"label": label or "", "status": status, "file": file})
        record.update({k: v for k, v in extra.items() if v not in (None, "")})
        self.data["episodes"][url] = record
        if save:
            self.save()

    def mark(self, ep, status, file="", **extra):
        self.mark_url(ep.url, ep.label, status, file, **extra)


def episode_done(prog, anime_dir, fname, url):
    """该集是否算已完成：进度为 done，且（进度里记录的文件 或 期望文件名）确实存在。

    放宽"期望文件名"这一条的缘由（v0.8.0）：外部纳管进来的文件叫别的名字
    （如 IDM 的 `牙狼garo-01-…mp4`），只认 `第NN集.mp4` 会让它们被重复下载；
    反过来，**删掉记录里的那个文件就会重新下载**——这也是手动补下的方式。

    注意：本函数只判"文件在不在"。**"文件在但版本更差"由 precheck 判定**（v0.10.0）：
    调用方在拿到 True 之后还会读一次清单声明值，决定是跳过还是重下。
    """
    if prog.status(url) != "done":
        return False
    recorded = prog.file_of(url)
    if recorded and (Path(anime_dir) / recorded).exists():
        return True
    return (Path(anime_dir) / f"{fname}.mp4").exists()


# ---------- 下载前的"要不要重下"判定（v0.10.0，设计见 §24） ----------

def _judge_redo(ep, record, referer_url, insecure=None, proxy=None, direct_first=False):
    """判定"这集要不要重下" → (action, reason, 清单声明值)。

    只对 m3u8 直链（内嵌播放器站点）生效：嗅探型列表页的 ep.url 是**播放页**，
    清单读不出来，保持 v0.9.0 的"文件在就跳过"。
    每次探测**新建 session**：实测一个 session 连续访问多条线路时，前几条死链会让
    会话降级到代理并污染后续请求（_probe_alive 里有同类注释与做法）。
    探测失败（网络/结构变化）时 probed 为空、action 恒为 skip —— 绝不因此重下。
    """
    if not is_m3u8_url(ep.url):
        return "skip", "非 m3u8 直链（嗅探型站点），按已完成跳过", {}
    session = build_session(referer=referer_url or ep.url, insecure=insecure,
                            proxy=proxy, direct_first=direct_first)
    probed = precheck.probe(session, ep.url)
    action, reason = precheck.decide(record, probed,
                                     line_name=getattr(ep, "line_name", "") or "")
    return action, reason, probed


def _backup_existing(anime_dir, old_name, new_name):
    """重下前把旧成品改名为 `<名>.bak` 保留（用户决策）→ (可否继续, 提示语)。

    同名（下载器自己命名的成品）改名失败时必须**放弃本次重下**：否则
    `shutil.move` 会把唯一一份覆盖掉。异名（外部纳管的 IDM 文件）失败只告警即可
    —— 新成品文件名不同，不存在覆盖问题（实测第01集那个旧文件被别的进程占着，
    改名/删除都被系统拒绝）。
    """
    if not old_name:
        return True, ""
    src = Path(anime_dir) / old_name
    if not src.exists():
        return True, ""
    target = src.with_name(src.name + ".bak")
    n = 2
    while target.exists():        # 已有 .bak 就往后排，绝不覆盖既有备份
        target = src.with_name(f"{src.name}.bak{n}")
        n += 1
    try:
        src.rename(target)
    except OSError as exc:
        if src.name == new_name:
            return False, f"旧成品改名失败（{exc}）且与新成品同名，放弃本次重下"
        return True, f"旧成品改名失败（{exc}），继续重下（文件名不同，不会覆盖）"
    return True, f"旧成品已保留为 {target.name}"


# ---------- 主流程 ----------

def _download_episode(ep, work_dir, fname, pick, insecure, proxy, concurrency,
                      max_try=3, referer_url="", direct_first=False):
    """单集：嗅探（或内嵌直链）→ 继承请求头 → 下载到独立工作目录。

    ep.url 是 m3u8 直链（内嵌播放器站点）时跳过嗅探，直接用 requests 下载；
    否则沿用嗅探流程。failover：主 URL 失败（嗅探不到/清单异常/切片失败）时
    按 alts 顺序换线重试；换线前清空工作目录，避免不同线路清单的续传进度串台。
    全部候选失败才抛错。
    返回 (成品路径, 清单声明值 dict)；声明值取自**成功那次**的 media 清单（v0.10.0）。
    """
    urls = [ep.url] + list(ep.alts or [])[:max(0, max_try - 1)]
    last_err = None
    for i, page_url in enumerate(urls):
        try:
            if i:
                print(f"[批量] 换线重试({i + 1}/{len(urls)}): {page_url}")
                shutil.rmtree(work_dir, ignore_errors=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            if is_m3u8_url(page_url):
                # 内嵌播放器直链：不需要浏览器，带页面 Referer 直接拉清单下载
                session = build_session(referer=referer_url or page_url,
                                        insecure=insecure, proxy=proxy,
                                        direct_first=direct_first)
                m3u8_url = page_url
            else:
                result = run_sniff(page_url, auto=pick, max_wait=90)
                session = session_from_sniff(result, insecure=insecure, proxy=proxy,
                                             direct_first=direct_first)
                m3u8_url = result.url
            playlist = load_playlist(session, m3u8_url)
            out_name = f"{fname}.mp4"
            run_download(session, playlist, out_dir=work_dir, concurrency=concurrency,
                         output_name=out_name)
            # 顺便把清单**声明**的分辨率/时长带回去（v0.10.0）：下载本身已经拉了清单，
            # 记下来零成本；下次判定"这集要不要重下"就有目标值可比（见 precheck.py）
            return work_dir / out_name, {
                "resolution": playlist.variant_resolution or "",
                "duration_sec": round(playlist.declared_duration, 1),
            }
        except Exception as e:   # KeyboardInterrupt 不在此列，中断仍直接退出
            last_err = e
            print(f"[批量] 尝试失败: {e}")
    raise last_err or RuntimeError("无可用的下载候选")


def _single_episode_plan(m3u8_url):
    """裸 m3u8 直链 → 单集 episode 计划（v0.11.0）。

    batch 支持直链入口的意义：把「get 直链」也纳入批量进度框架——
    下载管理器无论当初用哪种方式提交，续跑时都统一发 `batch <同一条URL>`，
    已完成跳过 / failover / 简介.md / 续传全部复用；该集没有播放页可嗅探，
    alts 为空（无备用线路）。

    标题：取 URL 路径最后一段的文件名去扩展名（去掉 query），
    为空时回退域名（如 `https://cdn.x.com/hls/index.m3u8` → `index`）。
    """
    path_part = urlparse(m3u8_url).path.rstrip("/").rsplit("/", 1)[-1]
    stem = path_part.rsplit(".", 1)[0] if "." in path_part else path_part
    # sanitize_name 永远不返回空串（空时给 "video"），所以先判 stem 再清洗，
    # 否则"路径为空时回退域名"这条分支永远走不到
    raw = stem if stem else urlparse(m3u8_url).netloc
    label = sanitize_name(raw) or "m3u8 单集"
    meta = {"description": "", "cover": "", "list_url": m3u8_url}
    return label, meta, [Episode(label=label, url=m3u8_url)]


def batch(list_url, interval=None, episodes=None, yes=False, pick=1, line=None,
          insecure=None, proxy=None, concurrency=None, out_dir=None, adopt=True):
    """批量下载入口（cli 层调用）。adopt=False 时不扫描外部已下载文件（v0.8.0）。"""
    interval = config.DOWNLOAD_INTERVAL if interval is None else interval
    site = sites.match(list_url)
    df = bool(site and site.proxy_policy == "direct_first")
    if site is not None:
        print(f"[批量] 已加载站点配置: {site.name}"
              f"（选线={site.line_preference}, failover={site.failover_max}, "
              f"出口={'直连优先' if df else '代理优先'}）")
    if is_m3u8_url(list_url):
        # 裸 m3u8 直链 = 单集批量（v0.11.0）：不解析列表页，直接构建一集，
        # 复用进度/跳过/failover/简介整套框架（管理器续跑统一走 batch）
        print("[批量] 输入为 m3u8 直链，按单集批量下载")
        title, meta, eps = _single_episode_plan(list_url)
    elif site is not None and site.player_embedded:
        # 内嵌播放器站点：直链不经页面（或仅部分在页面），需解析器（可能
        # 还要发 API 请求），先列线路再按选中线路建清单
        title, meta, eps = _parse_embedded_page(list_url, site, line,
                                                insecure=insecure, proxy=proxy)
    else:
        print(f"[批量] 解析列表页: {list_url}")
        title, meta, eps = parse_list_page(list_url, site)
    if not eps:
        raise RuntimeError("未从列表页解析到剧集链接")
    title = title or urlparse(list_url).path.strip("/").rsplit("/", 1)[-1]
    print(f"[批量] 标题: {title}")

    base = Path(out_dir) if out_dir else Path(config.OUTPUT_DIR)
    anime_dir = base / sanitize_name(title)
    anime_dir.mkdir(parents=True, exist_ok=True)
    info_path = anime_dir / "简介.md"
    # list_url 一并写入进度顶层（v0.11.0）：管理器「续跑」据此重新发起同一条命令，
    # 不再出现"缺少地址，无法续跑"
    prog = _BatchProgress(anime_dir / "批量进度.json", list_url=list_url)

    # 外部已下载文件纳管（v0.8.0）：用户可能用 IDM 等先下过一部分、文件名与下载器不同，
    # 逐集比对会重复下载。这里先扫番剧目录顶层，把能唯一对应到剧集的文件并入进度。
    # 放在下载循环之前（而非任务结束后）：否则本轮仍会把它们重下一遍（设计文档 §22.5）。
    if adopt:
        for report_line in external.format_report(
                external.adopt_into(anime_dir, eps, prog)):
            print(report_line)

    # 给"已在进度里/刚纳管"的成品补录分辨率、时长（v0.9.0）：只探缺信息的，
    # 结果写回进度，后续运行 0 成本。与 --no-adopt 无关——它只补记录、不改判定。
    mediainfo.fill_progress(prog, anime_dir)

    selected_idx = _select(eps, episodes, yes)
    if selected_idx is None:
        print("[批量] 已取消")
        return
    selected = [eps[i] for i in selected_idx]
    selected_urls = {ep.url for ep in selected}
    print(f"[批量] 已选 {len(selected)} 集，输出目录: {anime_dir}")

    # 续跑参数记忆（v0.11.0）：line/pick 写进 批量进度.json 顶层 resume_hint，
    # 管理器「续跑」据此带回，避免重新探活换线触发"线路变化→重下"的整季误重下
    prog.set_resume_hint(line, pick)

    # 封面图本地化（v0.7.3）：远程图床会先于视频失效，落盘到 番剧目录/image/
    # 供简介.md 相对引用；幂等（已有即复用）、失败只告警不中断（见 cover.py）。
    # 直链单集模式（v0.11.0）没有页面封面可抓，直接跳过
    if not is_m3u8_url(list_url):
        cover.prepare(anime_dir, meta, referer=meta.get("list_url") or list_url,
                      insecure=insecure, proxy=proxy, direct_first=df)

    # 集名 → 成品文件名（重名自动加后缀，避免多季同名覆盖）
    fnames, used = {}, set()
    for i, ep in enumerate(selected, 1):
        f = sanitize_name(ep.label) or f"EP{i:02d}"
        base_name, k = f, 2
        while f in used:
            f = f"{base_name}_{k}"
            k += 1
        used.add(f)
        fnames[ep.url] = f

    def flush_info():
        _write_info(info_path, title, meta, eps, prog.status_map(), selected_urls,
                    records=prog.data.get("episodes", {}))

    flush_info()
    print(f"[批量] 简介已生成: {info_path}")

    ok_list, fail_list, skip_list, redo_list = [], [], [], []
    for i, ep in enumerate(selected, 1):
        fname = fnames[ep.url]
        final_path = anime_dir / f"{fname}.mp4"
        if episode_done(prog, anime_dir, fname, ep.url):
            # 已完成 —— 但先按"清单声明值 vs 现有成品"判一次要不要重下（v0.10.0，§24）：
            # 站点上了更高清的源、或现有文件明显缺内容时自动换掉，旧成品改名 .bak 保留
            action, reason, probed = _judge_redo(
                ep, prog.data["episodes"].get(ep.url), list_url,
                insecure=insecure, proxy=proxy, direct_first=df)
            if probed:
                reason += (f"（清单声明 {probed.get('resolution') or '未声明'} / "
                           f"{probed.get('duration_sec') or 0:.0f} 秒）")
            if action == "skip":
                print(f"[批量] ({i}/{len(selected)}) {ep.label} 已完成，跳过 —— {reason}")
                skip_list.append(ep.label)
                continue
            recorded = prog.file_of(ep.url)
            extra = "" if recorded == final_path.name else f"（{recorded or final_path.name}）"
            print(f"[批量] ({i}/{len(selected)}) {ep.label} 已完成，但{reason} → 重新下载{extra}")
            can_go, note = _backup_existing(anime_dir, recorded, final_path.name)
            if note:
                print(f"        [旧成品] {note}")
            if not can_go:
                skip_list.append(ep.label)
                continue
            redo_list.append(ep.label)
        print(f"\n===== [第 {i}/{len(selected)} 集] {ep.label} =====")
        try:
            work_dir = anime_dir / "_work" / fname
            produced, declared = _download_episode(ep, work_dir, fname, pick,
                                                   insecure, proxy, concurrency,
                                                   max_try=site.failover_max if site else 3,
                                                   referer_url=list_url,
                                                   direct_first=df)
            shutil.move(str(produced), str(final_path))   # 成品扁平移入番剧目录
            shutil.rmtree(work_dir, ignore_errors=True)   # 清理中间切片
            # 顺手记录这个文件的实际分辨率/时长 + 它来自哪条线路（v0.9.0，
            # 供 简介.md 回看；外部纳管的文件不记线路——来源无从得知）；
            # 同时记下**清单声明的目标值**（v0.10.0）：下次判定"声明比声明"，
            # 站点把声明写错（实测声明 1080x608、实际 4K）也不会反复重下
            prog.mark(ep, "done", file=final_path.name,
                      line=getattr(ep, "line_name", "") or "",
                      declared_resolution=declared.get("resolution") or "",
                      declared_duration=declared.get("duration_sec") or "",
                      **mediainfo.probe(final_path))
            ok_list.append(ep.label)
            print(f"[批量] 完成: {final_path.name}")
        except Exception as e:
            print(f"[批量] 失败: {ep.label} — {e}")
            prog.mark(ep, "failed")
            fail_list.append(ep.label)
        finally:
            flush_info()   # 每集结束回写简介状态
        if i < len(selected):
            print(f"[批量] 等待 {interval} 秒后继续（Ctrl+C 中断，重跑同一命令续跑）")
            time.sleep(interval)

    # 收尾去重：换线路重下会让同一成品文件同时挂在旧线路 URL 与当前线路 URL 下，
    # 只留一条，免得"完成 X/X 集"虚高（v0.8.0 引入去重，这里补上循环后的这一次）
    dropped = external.dedupe_by_file(prog, [ep.url for ep in eps])
    if dropped:
        prog.save()
        print(f"[纳管] 清理了 {dropped} 条重复记录（同一成品文件被记在多个线路 URL 下）")

    print("\n===== 批量汇总 =====")
    print(f"完成 {len(ok_list)} / 失败 {len(fail_list)} / 跳过 {len(skip_list)}")
    if redo_list:
        print(f"其中重新下载 {len(redo_list)} 集（判定为清单有更高清版本 / 线路变化 / 疑似缺内容）: "
              + ", ".join(redo_list))
    if fail_list:
        print("失败集:", ", ".join(fail_list), "\n重跑同一命令只补失败/未完成集")
    print(f"简介: {info_path}")
    work_root = anime_dir / "_work"
    if work_root.is_dir() and not any(work_root.iterdir()):
        work_root.rmdir()   # 全部成功后清理空工作目录
