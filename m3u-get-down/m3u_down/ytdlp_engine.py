"""yt-dlp 引擎：主流站点（B站/YouTube 等）走 yt-dlp 库下载。

设计见《Design/项目设计文档.md》§18、§19。路由规则（顺序即优先级）：
  ① URL 命中 ytdlp_sites.json 的 engine 强制项 → 按强制项
  ② mode=list 时仅清单命中的域名走 yt-dlp；mode=auto（默认）时由 yt-dlp
     本地解析器判定（排除 GenericIE，联网前即可判定）
  ③ 否则回退自研引擎（sites/ 专用解析器 → 通用引擎）

yt-dlp 命中优先于 sites/ 的 unsupported 拦截（用户显式列进清单即放行）。
`import yt_dlp` 全部延迟到函数内部，未安装时本工具其余功能不受影响。
"""
import importlib.util
import json
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from . import config, cover
from .batch import Episode, _BatchProgress, _select, _write_info, episode_done
from .utils import sanitize_name

CFG_PATH = config.PROJECT_ROOT / "ytdlp_sites.json"
# 站点支持判定缓存（避免每次都加载 1700+ 解析器，~4s；按 yt-dlp 版本失效）
_CACHE_PATH = config.PROJECT_ROOT / ".ytdlp_hosts_cache.json"

# 「优先 ≤720P；没有 720P 则取能下到的最清晰」（未登录 B 站常只给 360/480P）
DEFAULT_FORMAT = ("bestvideo[height<=720]+bestaudio/best[height<=720]"
                  "/bestvideo+bestaudio/best")

# 仅用于「未安装 yt-dlp」时给出明确错误的高频站点（非路由依据）
_HINT_DOMAINS = ("bilibili.com", "b23.tv", "youtube.com", "youtu.be")

# 「读浏览器 cookie 失败」的错误特征（详见 _is_cookie_error）
_COOKIE_ERR_HINTS = ("dpapi", "app-bound", "app_bound", "decrypt",
                     "cookies database", "cookie database",
                     "object has no attribute 'decode'")

_DEFAULTS = {
    "_说明": "yt-dlp 引擎配置。mode=auto(默认,yt-dlp 有专用解析器的站点自动走它)"
             " / list(仅下面 sites 列出的域名走 yt-dlp)。cookies_file=cookies.txt 路径"
             "(非空优先于 cookies_from_browser); cookies_from_browser=从浏览器读 cookie 的"
             "浏览器名(edge/chrome/firefox, 留空=不用)。注意: 新版 Edge/Chrome 的 cookie 是"
             "App-Bound 加密(v20), yt-dlp 读不到(issue #10927), 建议改用"
             "浏览器扩展导出的 cookies.txt, 或改用 firefox(未加密)。"
             "format=清晰度选择(默认优先≤720P, 没有则取能下到的最清晰)。"
             "sites=仅放需要覆盖默认行为的站点(engine=m3u 强制自研 / ytdlp 强制 yt-dlp, "
             "另可覆盖 format/cookies_from_browser/cookies_file/proxy_policy/extra_opts); "
             "auto 模式无需在此列域名。已预置：B站(直连优先, 国内 CDN) + 4 个自研站点"
             "(engine=m3u 守卫)。extra_opts=透传给 yt-dlp 的原始选项(逃生舱), "
             "默认已开启 JS 运行时 deno/node 与 EJS 挑战脚本(YouTube 必需, 缺了只告警不报错)。",
    "enabled": True,
    "mode": "auto",
    "cookies_from_browser": "edge",
    "cookies_file": "",
    "format": DEFAULT_FORMAT,
    "merge_output_format": "mp4",
    # YouTube 需要 JS 运行时（yt-dlp 默认只启用 deno）；deno 优先、没装则用 node，
    # 两个都没有时只会告警，不影响其它站点。
    # remote_components：允许下载 EJS 挑战求解脚本（YouTube 必要，首次自动拉取并缓存
    # 到 ~/.cache/yt-dlp/challenge-solver；拉不到只会告警，其他站点无关）。
    "extra_opts": {"js_runtimes": {"deno": {}, "node": {}},
                   "remote_components": ["ejs:github"]},
    # 仅「守卫」条目：已精修的 4 个自研站点 pin 成 m3u，避免被 yt-dlp 抢走
    "sites": [
        # B 站国内 CDN 与 ikanbot 同性质（实测代理出口反而可能被歧视），直连优先
        {"name": "bilibili", "domains": ["bilibili.com", "b23.tv", "acg.tv"],
         "proxy_policy": "direct_first"},
        {"name": "ikanbot", "domains": ["ikanbot.com"], "engine": "m3u"},
        {"name": "mvffm", "domains": ["mvffm.net", "movieffm.net"], "engine": "m3u"},
        {"name": "eacg", "domains": ["eacg.net"], "engine": "m3u"},
        {"name": "youknow", "domains": ["youknow.tv"], "engine": "m3u"},
    ],
}


# ---------- 配置加载与匹配 ----------

def load_config():
    """读取 ytdlp_sites.json（不存在则生成默认），未知键忽略、坏文件容错。"""
    data = dict(_DEFAULTS)
    if CFG_PATH.exists():
        try:
            user = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            for k in _DEFAULTS:
                if k in user:
                    data[k] = user[k]
        except Exception:
            print(f"[yt-dlp] {CFG_PATH.name} 解析失败，使用默认配置")
    else:
        try:  # 首次运行自动生成，便于用户按需修改
            CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"[yt-dlp] 已生成默认配置文件: {CFG_PATH}")
        except Exception:
            pass
    return data


def _host(url):
    return urlparse(url or "").netloc.lower().split("@")[-1].split(":")[0]


def match(url, cfg=None):
    """按域名后缀匹配站点覆盖项 → dict 或 None（语义同 sites.py）。"""
    cfg = cfg or load_config()
    host = _host(url)
    if not host:
        return None
    for site in cfg.get("sites") or []:
        if not isinstance(site, dict):
            continue
        for dom in site.get("domains") or []:
            dom = str(dom).lower().lstrip(".")
            if host == dom or host.endswith("." + dom):
                return site
    return None


def available():
    """yt-dlp 是否已安装（延迟导入，未装不影响其它功能）。"""
    return importlib.util.find_spec("yt_dlp") is not None


def ensure_available():
    """走 yt-dlp 前的依赖检查；未安装则抛出带安装提示的错误。"""
    if not available():
        raise RuntimeError(
            "该站点需要 yt-dlp 引擎，但未安装。请先安装后重试：\n"
            "    py -m pip install -U yt-dlp\n"
            "（yt-dlp 覆盖 B 站/YouTube 等 1800+ 站点，见 https://github.com/yt-dlp/yt-dlp）")


def is_supported_by_ytdlp(url):
    """本地判定 yt-dlp 是否有该 URL 的专用解析器（联网前，排除通用兜底）。

    加载全部解析器较慢（~4s），故按 host + yt-dlp 版本缓存判定结果。
    """
    host = _host(url)
    if not host:
        return False
    try:
        from yt_dlp.version import __version__ as ver
    except Exception:
        ver = "?"
    cache = _load_host_cache()
    ent = cache.get(host)
    if isinstance(ent, dict) and ent.get("v") == ver:
        return bool(ent.get("supported"))
    print(f"[yt-dlp] 首次分析站点 {host}，正在匹配 yt-dlp 解析器列表（仅此一次）...")
    supported = _scan_extractors(url)
    cache[host] = {"v": ver, "supported": supported}
    _save_host_cache(cache)
    return supported


def _scan_extractors(url):
    try:
        from yt_dlp.extractor import gen_extractors
    except Exception:
        return False
    for ie in gen_extractors():
        try:
            name = ie.ie_key()
            if name in ("Generic", "generic"):
                continue   # 通用兜底不算「专用支持」
            if ie.suitable(url):
                return True
        except Exception:
            continue
    return False


def _load_host_cache():
    try:
        if _CACHE_PATH.exists():
            d = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save_host_cache(cache):
    try:
        _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=0),
                               encoding="utf-8")
    except Exception:
        pass


def route(url):
    """路由判定：返回 "ytdlp"（交给 yt-dlp）或 "m3u"（走自研引擎）。"""
    cfg = load_config()
    if not cfg.get("enabled", True):
        return "m3u"
    site = match(url, cfg)
    if site:
        eng = str(site.get("engine") or "").strip()
        if eng == "m3u":
            return "m3u"          # 显式守卫：即使 yt-dlp 支持也走自研
        if eng == "ytdlp":
            return "ytdlp"
    if str(cfg.get("mode") or "auto").lower() == "list":
        return "ytdlp" if site else "m3u"
    # auto：由 yt-dlp 解析器表判定
    if available():
        return "ytdlp" if is_supported_by_ytdlp(url) else "m3u"
    # 未安装 yt-dlp：常见站直接交给引擎层报「需安装」，避免自研引擎撞墙
    host = _host(url)
    if any(host == d or host.endswith("." + d) for d in _HINT_DOMAINS):
        return "ytdlp"
    return "m3u"


# ---------- yt-dlp 选项与出口 ----------

def _pick(key, cfg, site):
    """站点覆盖优先，否则用全局配置。"""
    if site and site.get(key) not in (None, ""):
        return site.get(key)
    return cfg.get(key)


def _parse_browser(spec):
    """edge / chrome:Profile 1 → yt-dlp 的 cookiesfrombrowser 元组。"""
    spec = str(spec or "").strip()
    if not spec:
        return None
    if ":" in spec:
        browser, profile = spec.split(":", 1)
        return (browser.strip(), profile.strip() or None, None, None)
    return (spec, None, None, None)


class _Logger:
    """yt-dlp 日志转译：压掉原生信息，统一为本工具风格。"""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if not str(msg).startswith("[debug] "):
            print(f"[yt-dlp] 警告: {msg}")

    def error(self, msg):
        # cookie 读取失败的报错不直接打印：_extract 会降级重试并给出一次性的
        # 中文提示（否则会先喊几声“错误”再下载成功，白挨一下）。真到了无法恢复
        # 的地步，异常会传到 CLI 顶层打印 [失败]。
        if _is_cookie_error(msg):
            return
        print(f"[yt-dlp] 错误: {msg}")


_cookie_warned = [False]


def _is_cookie_error(err):
    """判断异常是否属于"读浏览器 cookie 失败"（应与站点问题区分）。

    yt-dlp 的报错文案随版本/浏览器变化，这里做宽松匹配：
      - Could not copy Chrome cookie database（浏览器正占用数据库）
      - Failed to decrypt with DPAPI ...（yt-dlp #10927：新版 Edge/Chrome 的
        App-Bound 加密 v20，第三方读不到）
      - 'NoneType' object has no attribute 'decode'（同一 issue 的另一种表现）
    误判代价很低：重试只是"去掉 cookie 再跑一次"，真失败仍是同一个错误。
    """
    s = str(err).lower()
    if any(h in s for h in _COOKIE_ERR_HINTS):
        return True
    return "cookie" in s and any(w in s for w in ("could not", "unable", "failed", "error"))


def _cookie_failure(err, opts):
    """该异常是否由 cookie 读取/加载失败引起（浏览器 cookie 库 或 cookies.txt）。

    cookies.txt 打不开时，yt-dlp 抛出的报错只剩 `[Errno 2] No such file or
    directory: '...'`，已丢掉“cookie”语境，只能用路径特征补判。
    """
    if _is_cookie_error(err):
        return True
    cfile = str(opts.get("cookiefile") or "")
    s = str(err)
    return bool(cfile) and cfile in s and any(
        w in s.lower() for w in ("no such file", "errno 2", "cannot find"))


def _extract(opts, url, download):
    """调用 yt-dlp 提取/下载；cookie 读取失败时自动降级为无 cookie 重试。

    cookie 数据库被浏览器锁定 / 新版 App-Bound 加密都可能读不到，不应让
    整个下载失败（无 cookie 只是清晰度/会员内容受限）。
    """
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download)
    except Exception as e:
        # 浏览器 cookie 与 cookies.txt 两神来源都算「cookie 读不到」，都应降级重试
        if (opts.get("cookiesfrombrowser") or opts.get("cookiefile")) and _cookie_failure(e, opts):
            if not _cookie_warned[0]:
                _cookie_warned[0] = True
                print("[yt-dlp] 注意：cookie 读取失败（cookies.txt 路径不对/已过期，或浏览器正"
                      "占用数据库；新版 Edge/Chrome 的 App-Bound 加密第三方也读不到，"
                      "见 yt-dlp issue #10927）。已改用无 cookie 继续——清晰度/会员内容可能受限。")
                print("[yt-dlp]       建议：用扩展导出 cookies.txt（Edge/Chrome 选 "
                      "\"Get cookies.txt LOCALLY\"）后把路径填到 ytdlp_sites.json 的 "
                      "cookies_file；或装个 Firefox 登录一次并把 cookies_from_browser "
                      "设为 firefox（Firefox 的 cookie 未加密）。"
                      "详见 使用指南.md「cookies.txt 导出与使用」。")
            o2 = dict(opts)
            o2.pop("cookiesfrombrowser", None)
            o2.pop("cookiefile", None)
            with yt_dlp.YoutubeDL(o2) as ydl:
                return ydl.extract_info(url, download=download)
        raise


def _decide_proxy(cfg, site, url, proxy_override, insecure):
    """决定本次 yt-dlp 用代理还是直连（复用 probe_proxy 的出口取舍思路）。

    proxy_override 为 None 时用 config.PROXY；为 "" 表示用户要求纯直连。
    站点可配 proxy_policy：proxy_first（默认，先试代理）/ direct_first（先试直连）。
    """
    if proxy_override is not None:
        return proxy_override or None   # 显式指定（含空串）时不做探测
    proxy = config.PROXY
    if not proxy:
        return None
    df = str(_pick("proxy_policy", cfg, site) or "proxy_first").lower() == "direct_first"
    try:
        from .session import probe_proxy
        chosen = probe_proxy(url, direct_first=df, insecure=insecure)
    except Exception:
        chosen = None
    if chosen == "direct":
        return None
    return proxy


def base_opts(cfg, site, proxy, insecure, concurrency):
    """构造 yt-dlp 通用选项（不含输出模板与进度钩子）。"""
    opts = {
        "format": _pick("format", cfg, site) or DEFAULT_FORMAT,
        "merge_output_format": _pick("merge_output_format", cfg, site) or "mp4",
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "consoletitle": False,
        "retries": config.RETRY_TIMES,
        "fragment_retries": config.RETRY_TIMES,
        "socket_timeout": config.TIMEOUT[1],
        "concurrent_fragment_downloads": concurrency or config.CONCURRENCY,
        "ignoreerrors": False,
        "noplaylist": False,
        "logger": _Logger(),
    }
    if config.FFMPEG_PATH:
        opts["ffmpeg_location"] = config.FFMPEG_PATH   # DASH 音视频合并依赖 ffmpeg
    if insecure:
        opts["nocheckcertificate"] = True
    if proxy:
        opts["proxy"] = proxy
    cfile = _pick("cookies_file", cfg, site)
    if cfile:
        opts["cookiefile"] = str(cfile)
    else:
        cb = _parse_browser(_pick("cookies_from_browser", cfg, site))
        if cb:
            opts["cookiesfrombrowser"] = cb
    extra = _pick("extra_opts", cfg, site)
    if isinstance(extra, dict):
        opts.update(extra)          # 逃生舱：允许覆盖任意 yt-dlp 原生选项
    return opts


def _make_hook(label):
    """进度钩子：把 yt-dlp 的下载进度渲染成本工具风格的进度条。"""
    from .utils import render_progress
    state = {"t0": None}

    def hook(d):
        status = d.get("status")
        if status == "downloading":
            if state["t0"] is None:
                state["t0"] = time.monotonic()
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            elapsed = time.monotonic() - state["t0"]
            bar = render_progress(int(done), int(total or 1), done, elapsed)
            print(f"\r[下载] {label} {bar}", end="", flush=True)
        elif status == "finished":
            print(f"\r[下载] {label} 已完成，正在合并 ..." + " " * 30)
    return hook


def _iter_entries(info):
    """从 extract_info 结果里取条目列表（playlist 或单视频）。"""
    if not info:
        return []
    entries = info.get("entries")
    if entries is None:
        return [info]
    out = []
    for e in entries:
        if isinstance(e, dict):
            out.append(e)
    return out


# ---------- 单视频下载（get / sniff / play 命中时） ----------

def download_single(url, out_dir=None, proxy=None, insecure=None, concurrency=None):
    """下载单个视频（单集命令路径），产物扁平为 output_dir/<标题>.mp4。

    noplaylist=True：只下 URL 指向的那一个视频（合集/番剧请用 batch）；
    探测到是合集时打印一行提示。
    """
    ensure_available()

    cfg = load_config()
    site = match(url, cfg)

    insecure_v = config.INSECURE if insecure is None else insecure
    px = _decide_proxy(cfg, site, url, proxy, insecure_v)
    base = Path(out_dir) if out_dir else Path(config.OUTPUT_DIR)
    base.mkdir(parents=True, exist_ok=True)

    _maybe_hint_playlist(cfg, site, url, px, insecure_v, concurrency)

    # 实际下载：先下到工作目录，完成后按真实标题命名移出
    work = base / "_work" / f"ytdlp_{int(time.time() * 1000)}"
    work.mkdir(parents=True, exist_ok=True)
    dl_opts = base_opts(cfg, site, px, insecure_v, concurrency)
    dl_opts.update({
        "noplaylist": True,          # 只下 URL 指向的那个视频（整季用 batch）
        "outtmpl": str(work / "%(title)s.%(ext)s"),
        "progress_hooks": [_make_hook("")],
    })
    try:
        info = _extract(dl_opts, url, download=True)
        produced = _produced_file(info, work)
        if not produced:
            raise RuntimeError("yt-dlp 未产出文件")
        title = info.get("title") or _host(url)
        final = _unique_path(base, sanitize_name(title), produced.suffix)
        shutil.move(str(produced), str(final))
        print(f"[yt-dlp] 完成: {final}")
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _cleanup_work_root(work)


def _maybe_hint_playlist(cfg, site, url, proxy, insecure, concurrency):
    """轻量探测是否为多条目合集，是则提示改用 batch（失败不影响下载）。"""
    opts = base_opts(cfg, site, proxy, insecure, concurrency)
    opts.update({"noplaylist": True, "skip_download": True,
                 "extract_flat": "in_playlist", "quiet": True})
    try:
        info = _extract(opts, url, download=False)
        if info.get("_type") == "playlist" and len(_iter_entries(info)) > 1:
            print(f"[yt-dlp] 检测到合集/番剧（{len(_iter_entries(info))} 个条目）；"
                  f"整季下载请改用: m3u_down batch \"{url}\"")
    except Exception:
        pass


def _cleanup_work_root(work):
    """删除空的工作根目录（work 已是 base/_work/子目录）。"""
    try:
        work.parent.rmdir()
    except OSError:
        pass


def _produced_file(info, work_dir=None):
    """从 yt-dlp 的 info / 工作目录里取实际产出的文件路径。"""
    for e in _iter_entries(info):
        for d in (e.get("requested_downloads") or []):
            p = d.get("filepath")
            if p and Path(p).exists():
                return Path(p)
    p = info.get("filepath") or info.get("_filename")
    if p and Path(p).exists():
        return Path(p)
    if work_dir:   # 兑底：取工作目录里体积最大的非临时文件（合并后成品）
        cands = [f for f in Path(work_dir).glob("*")
                 if f.is_file() and not f.name.endswith((".part", ".ytdl"))]
        if cands:
            return max(cands, key=lambda f: f.stat().st_size)
    return None


def _unique_path(base, name, suffix):
    """重名自动加序号，避免覆盖已有成品。"""
    target = base / f"{name}{suffix}"
    k = 2
    while target.exists():
        target = base / f"{name}_{k}{suffix}"
        k += 1
    return target


# ---------- 批量下载（batch 命中时） ----------

def _entry_label(entry, idx):
    """条目名：标题 → 集号 → EPxx。"""
    for key in ("title", "fulltitle", "id"):
        v = str(entry.get(key) or "").strip()
        if v:
            return v
    num = entry.get("episode_number") or entry.get("playlist_index")
    return f"EP{int(num or idx):02d}"


def list_entries(url, cfg, site, proxy, insecure, concurrency):
    """列出合集/番剧条目 → ([Episode], 标题, meta)。

    extract_flat='in_playlist'：只取条目标题不逐条解析，快。
    """
    opts = base_opts(cfg, site, proxy, insecure, concurrency)
    opts.update({"skip_download": True, "extract_flat": "in_playlist",
                 "noplaylist": False})
    info = _extract(opts, url, download=False)
    entries = _iter_entries(info)
    eps = []
    for i, e in enumerate(entries, 1):
        ep_url = e.get("url") or e.get("webpage_url") or e.get("id")
        eps.append(Episode(label=_entry_label(e, i), url=str(ep_url),
                           alts=None, line=None))
    title = info.get("title") or _host(url)
    meta = {
        "description": info.get("description") or "",
        "cover": info.get("thumbnail") or "",
        "list_url": url,
    }
    return eps, title, meta


def describe(url, proxy=None, insecure=None, concurrency=None):
    """仅列出标题与条目（sniff --no-download 命中 yt-dlp 站点时）。"""
    ensure_available()
    cfg = load_config()
    site = match(url, cfg)
    insecure_v = config.INSECURE if insecure is None else insecure
    px = _decide_proxy(cfg, site, url, proxy, insecure_v)
    eps, title, meta = list_entries(url, cfg, site, px, insecure_v, concurrency)
    print(f"[yt-dlp] 标题: {title}")
    if len(eps) <= 1:
        print("[yt-dlp] 单视频")
        return
    print(f"[yt-dlp] 共 {len(eps)} 个条目:")
    for i, ep in enumerate(eps[:50], 1):
        print(f"  {i:>3}. {ep.label}")
    if len(eps) > 50:
        print(f"  ...（共 {len(eps)} 条）")


def download_entries(url, interval=None, episodes=None, yes=False,
                     proxy=None, insecure=None, concurrency=None, out_dir=None):
    """批量下载入口（batch 命中 yt-dlp 站点时调用）。

    复用 batch.py 的选集交互、简介.md、批量进度.json 与 _work/ 约定，
    实现中断续跑（已完成集按「进度标记 + 成品存在」跳过）。
    """
    ensure_available()

    interval = config.DOWNLOAD_INTERVAL if interval is None else interval
    cfg = load_config()
    site = match(url, cfg)
    insecure_v = config.INSECURE if insecure is None else insecure
    px = _decide_proxy(cfg, site, url, proxy, insecure_v)

    print(f"[yt-dlp] 引擎: {'代理' if px else '直连'}"
          f"（cookie={'文件' if _pick('cookies_file', cfg, site) else _pick('cookies_from_browser', cfg, site) or '未启用'}）")
    print(f"[yt-dlp] 解析合集/番剧: {url}")
    eps, title, meta = list_entries(url, cfg, site, px, insecure_v, concurrency)
    if not eps:
        raise RuntimeError("yt-dlp 未解析到任何条目")
    print(f"[yt-dlp] 标题: {title}")

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

    # 封面图本地化（v0.7.3）：与 batch.py 同一套约定，落盘 番剧目录/image/。
    # px 为 None 表示探测结论是直连 → 传 "" 不让 build_session 再回落配置代理。
    cover.prepare(anime_dir, meta, referer=url, insecure=insecure_v,
                  proxy=px or "", direct_first=False)

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

    ok_list, fail_list, skip_list = [], [], []
    for i, ep in enumerate(selected, 1):
        fname = fnames[ep.url]
        final_path = anime_dir / f"{fname}.mp4"
        if episode_done(prog, anime_dir, fname, ep.url):
            print(f"[批量] ({i}/{len(selected)}) {ep.label} 已完成，跳过")
            skip_list.append(ep.label)
            continue
        print(f"\n===== [第 {i}/{len(selected)} 集] {ep.label} =====")
        try:
            _download_one(cfg, site, ep, anime_dir, fname, px,
                          insecure_v, concurrency)
            prog.mark(ep, "done", file=final_path.name)
            ok_list.append(ep.label)
            print(f"[批量] 完成: {final_path.name}")
        except Exception as e:
            print(f"[批量] 失败: {ep.label} — {e}")
            prog.mark(ep, "failed")
            fail_list.append(ep.label)
        finally:
            flush_info()
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
        work_root.rmdir()


def _download_one(cfg, site, ep, anime_dir, fname, proxy, insecure,
                  concurrency):
    """单集下载：yt-dlp 下到 _work/集名/，再移动成 番剧目录/集名.mp4。"""
    final_path = anime_dir / f"{fname}.mp4"
    work = anime_dir / "_work" / fname
    work.mkdir(parents=True, exist_ok=True)
    opts = base_opts(cfg, site, proxy, insecure, concurrency)
    opts.update({
        "noplaylist": True,
        "outtmpl": str(work / "%(title)s.%(ext)s"),
        "progress_hooks": [_make_hook(f"{fname} ")],
        "continuedl": True,          # 支持 yt-dlp 自身的 .part 续传
    })
    try:
        info = _extract(opts, ep.url, download=True)
        produced = _produced_file(info, work)
        if not produced:
            raise RuntimeError("yt-dlp 未产出文件")
        shutil.move(str(produced), str(final_path))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return final_path
