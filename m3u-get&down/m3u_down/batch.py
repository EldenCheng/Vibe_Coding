"""列表页批量下载：解析剧集清单 → 生成简介.md → 逐集嗅探下载。

设计见《Design/项目设计文档.md》§10.3：
- 列表页两级解析（requests 正则优先，Playwright DOM 兜底）
- 模板分组取最大组 + 列表页 ID 过滤 + 去重 + 自然排序
- 每集独立工作目录（集间隔离，避免续传数据串台），成品扁平移动为 番剧名/集名.mp4
- 批量进度.json 记录状态，已完成集跳过（中断续跑），单集失败不阻塞
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

from . import config, sites
from .downloader import run as run_download
from .parser import load_playlist
from .session import DEFAULT_UA, session_from_sniff
from .sniffer import sniff as run_sniff
from .utils import sanitize_name

_LINK_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Episode:
    label: str   # 集名（链接文本或从 URL 推断）
    url: str     # 播放页地址
    alts: list = None   # 备选线路播放页列表（主 URL 失败时按序 failover）


# ---------- 列表页解析 ----------

def _fetch_html(url):
    """requests 拉取页面文本，中文站无 charset 声明时用内容探测兜底。"""
    r = requests.get(url, headers={"User-Agent": DEFAULT_UA}, timeout=config.TIMEOUT)
    r.raise_for_status()
    if (r.encoding or "").lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or r.encoding
    return r.text, r.url


def _render_html(url):
    """Playwright 兜底：JS 渲染的列表页在浏览器里展开后取 DOM。"""
    from playwright.sync_api import sync_playwright
    from .sniffer import context_kwargs, launch_browser
    with sync_playwright() as p:
        browser = launch_browser(p)
        context = browser.new_context(**context_kwargs())
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
    """提取番剧标题 / 剧情简介 / 封面图 URL（site 提供简介清洗规则）。"""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
    title = _deep_unescape(_TAG_RE.sub("", m.group(1))).strip() if m else ""
    if not title:
        m = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
        if m:
            title = m.group(1).strip()
            # 去掉"在线观看/高清视频"及站点后缀等噪声
            title = re.split(r"在线观看|高清|全集", title)[0].split("-")[0].strip("《》 -，,")
    desc = _meta_content(html_text, ("description", "og:description"))
    desc = _deep_unescape(desc or "")
    if site is not None:
        desc = site.clean_desc(desc)
    elif "|" in desc:   # 通用兜底：去掉站点拼接的"剧情摘要 | 站点名"后缀
        desc = desc.split("|")[0].strip()
    cover = _meta_content(html_text, ("og:image",))
    if cover:
        # 容错：修复部分站点把域名和图片 URL 直接拼接的畸形地址
        i = cover.rfind("http")
        if i > 0:
            cover = cover[i:]
    return title, {"description": _deep_unescape(desc or ""), "cover": cover or ""}


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
    html_text, base = _fetch_html(list_url)
    title, meta = _extract_info(html_text, site)
    eps = _extract_episodes(html_text, base, list_url, site)
    if not eps:
        print("[批量] requests 未解析到剧集链接，尝试浏览器渲染兜底 ...")
        html_text, base = _render_html(list_url)
        title, meta = _extract_info(html_text, site)
        eps = _extract_episodes(html_text, base, list_url, site)
    meta["list_url"] = list_url
    return title, meta, eps


# ---------- 简介页 ----------

def _write_info(path, title, meta, eps, status_by_url, selected_urls):
    """生成/回写 简介.md（状态随下载进度更新，直接整文件重写）。"""
    lines = [f"# {title}", ""]
    if meta.get("cover"):
        lines += [f"![封面]({meta['cover']})", ""]
    lines += [f"> 来源列表页：{meta.get('list_url', '')}", ""]
    if meta.get("description"):
        lines += ["## 剧情简介", "", meta["description"], ""]
    lines += ["## 剧集清单", "", "| # | 集名 | 链接 | 状态 |",
              "|---|------|------|------|"]
    for i, ep in enumerate(eps, 1):
        if status_by_url.get(ep.url) == "done":
            st = "完成"
        elif status_by_url.get(ep.url) == "failed":
            st = "失败"
        elif ep.url in selected_urls:
            st = "待下载"
        else:
            st = "未选择"
        lines.append(f"| {i} | {ep.label} | <{ep.url}> | {st} |")
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
        print(f"  {i:>3}. {ep.label}   {ep.url}")
    if spec:
        # 显式范围优先于 --yes（脚本化指定集数时不能被"全下"覆盖）
        return _parse_spec(spec, n)
    if yes:
        return list(range(n))
    raw = input("回车全部下载 / 输入范围如 1-12,15 / q 退出: ").strip()
    if raw.lower() in ("q", "quit", "exit"):
        return None
    return list(range(n)) if not raw else _parse_spec(raw, n)


# ---------- 批量进度 ----------

class _BatchProgress:
    """批量进度.json：按剧集 URL 记录状态，重跑自动跳过已完成。"""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {"episodes": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def status(self, url):
        return self.data["episodes"].get(url, {}).get("status")

    def status_map(self):
        """{剧集URL: 状态}，供简介页状态表使用。"""
        return {u: v.get("status") for u, v in self.data.get("episodes", {}).items()}

    def mark(self, ep, status, file=""):
        self.data["episodes"][ep.url] = {"label": ep.label, "status": status,
                                         "file": file}
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                             encoding="utf-8")


# ---------- 主流程 ----------

def _download_episode(ep, work_dir, fname, pick, insecure, proxy, concurrency,
                      max_try=3):
    """单集：嗅探 → 继承请求头 → 下载到独立工作目录，返回成品工作路径。

    failover：主 URL 失败（嗅探不到/清单异常/切片失败）时按 alts 顺序换线重试；
    换线前清空工作目录，避免不同线路清单的续传进度串台。全部候选失败才抛错。
    """
    urls = [ep.url] + list(ep.alts or [])[:max(0, max_try - 1)]
    last_err = None
    for i, page_url in enumerate(urls):
        try:
            if i:
                print(f"[批量] 换线重试({i + 1}/{len(urls)}): {page_url}")
                shutil.rmtree(work_dir, ignore_errors=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            result = run_sniff(page_url, auto=pick, max_wait=90)
            session = session_from_sniff(result, insecure=insecure, proxy=proxy)
            playlist = load_playlist(session, result.url)
            out_name = f"{fname}.mp4"
            run_download(session, playlist, out_dir=work_dir, concurrency=concurrency,
                         output_name=out_name)
            return work_dir / out_name
        except Exception as e:   # KeyboardInterrupt 不在此列，中断仍直接退出
            last_err = e
            print(f"[批量] 尝试失败: {e}")
    raise last_err or RuntimeError("无可用的下载候选")


def batch(list_url, interval=None, episodes=None, yes=False, pick=1,
          insecure=None, proxy=None, concurrency=None, out_dir=None):
    """批量下载入口（cli 层调用）。"""
    interval = config.DOWNLOAD_INTERVAL if interval is None else interval
    site = sites.match(list_url)
    if site is not None:
        print(f"[批量] 已加载站点配置: {site.name}"
              f"（选线={site.line_preference}, failover={site.failover_max}）")
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
    prog = _BatchProgress(anime_dir / "批量进度.json")

    selected_idx = _select(eps, episodes, yes)
    if selected_idx is None:
        print("[批量] 已取消")
        return
    selected = [eps[i] for i in selected_idx]
    selected_urls = {ep.url for ep in selected}
    print(f"[批量] 已选 {len(selected)} 集，输出目录: {anime_dir}")

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
        _write_info(info_path, title, meta, eps, prog.status_map(), selected_urls)

    flush_info()
    print(f"[批量] 简介已生成: {info_path}")

    ok_list, fail_list, skip_list = [], [], []
    for i, ep in enumerate(selected, 1):
        fname = fnames[ep.url]
        final_path = anime_dir / f"{fname}.mp4"
        if prog.status(ep.url) == "done" and final_path.exists():
            print(f"[批量] ({i}/{len(selected)}) {ep.label} 已完成，跳过")
            skip_list.append(ep.label)
            continue
        print(f"\n===== [第 {i}/{len(selected)} 集] {ep.label} =====")
        try:
            work_dir = anime_dir / "_work" / fname
            produced = _download_episode(ep, work_dir, fname, pick,
                                         insecure, proxy, concurrency,
                                         max_try=site.failover_max if site else 3)
            shutil.move(str(produced), str(final_path))   # 成品扁平移入番剧目录
            shutil.rmtree(work_dir, ignore_errors=True)   # 清理中间切片
            prog.mark(ep, "done", file=final_path.name)
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

    print("\n===== 批量汇总 =====")
    print(f"完成 {len(ok_list)} / 失败 {len(fail_list)} / 跳过 {len(skip_list)}")
    if fail_list:
        print("失败集:", ", ".join(fail_list), "\n重跑同一命令只补失败/未完成集")
    print(f"简介: {info_path}")
    work_root = anime_dir / "_work"
    if work_root.is_dir() and not any(work_root.iterdir()):
        work_root.rmdir()   # 全部成功后清理空工作目录
