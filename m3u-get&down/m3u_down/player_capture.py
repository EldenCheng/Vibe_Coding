"""播放器兜底模式：打开真实播放页旁观浏览器拉流，切片落盘后合并。

适用：直接下载被拒（复杂防盗链），但浏览器能正常播放的场景。
原理：被动旁观（response.body()），不改写、不阻塞任何请求，
对站点 CORS / 流式播放零干扰；耗时约等于播放时长，--speed 可倍速拉快。
"""
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import config
from .downloader import finalize
from .parser import DRMError, parse
from .session import (build_session, headers_from_request,
                      set_cookies_from_playwright)
from .sniffer import context_kwargs, launch_browser
from .utils import ext_from_url, is_m3u8_url, looks_like_segment, render_progress

# 裸 m3u8 直链的本地代播页（能否播放取决于 CDN 是否允许跨域）
_LOCAL_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>m3u 本地播放器</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script></head>
<body><video id="v" controls autoplay style="width:100%"></video>
<script>
const src = %URL%;
const v = document.getElementById('v');
if (Hls.isSupported()) {
  const hls = new Hls(); hls.loadSource(src); hls.attachMedia(v);
  hls.on(Hls.Events.ERROR, (e, d) => { if (d.fatal) document.title = '播放失败: ' + d.details; });
} else if (v.canPlayType('application/vnd.apple.mpegurl')) { v.src = src; }
</script></body></html>"""


def build_local_player_page(m3u8_url):
    """裸 m3u8 → 生成本地 hls.js 播放页，返回 file:// 地址。"""
    path = Path(tempfile.gettempdir()) / "m3u_local_player.html"
    path.write_text(_LOCAL_PAGE.replace("%URL%", repr(m3u8_url)), encoding="utf-8")
    return path.as_uri()


def _set_playback_rate(page, rate):
    """把页面里所有 video 元素调到指定倍速（拉快切片请求，缩短等待）。"""
    try:
        page.evaluate(
            "(r) => document.querySelectorAll('video').forEach("
            "v => { try { v.playbackRate = r; } catch (e) {} })",
            rate)
    except Exception:
        pass


def capture(page_url, out_dir=None, speed=1.0, max_wait=7200, insecure=None,
            proxy=None, headless=False):
    """打开播放页旁观播放，落盘目标切片，结束后补拉缺失并合并。"""
    out_dir = (Path(out_dir) if out_dir
               else Path(config.OUTPUT_DIR) / f"play_{time.strftime('%Y%m%d_%H%M%S')}")
    seg_dir = out_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "playlists": {},    # url -> 清单文本
        "headers": {},      # url -> 浏览器请求头（供补拉继承）
        "chosen": None,     # (url, Playlist)
        "expected": None,   # {seg.url: Segment}
        "init_url": None,
        "init_fname": None,
        "cookies": [],
        "drm": None,
    }
    saved = {}              # 切片序号 -> 文件名
    bodies = {}             # 清单解析前的切片体缓存
    stat = {"bytes": 0, "t0": None}  # 进度条统计：已捕获字节 / 计时起点

    def resolve_playlist():
        """在已捕获清单中选切片最多的 media 清单，建立期望集合。"""
        best = None
        for url, text in state["playlists"].items():
            try:
                pl = parse(text, url)
            except DRMError as e:
                state["drm"] = str(e)
                return
            except Exception:
                continue
            if pl.segments and (best is None or len(pl.segments) > len(best[1].segments)):
                best = (url, pl)
        if best is None:
            return
        url, pl = best
        state["chosen"] = best
        state["expected"] = {seg.url: seg for seg in pl.segments}
        state["init_url"] = pl.init_url
        state["t0"] = time.time()
        (out_dir / "playlist.m3u8").write_text(pl.raw, encoding="utf-8")
        # 清单就位后，把先前缓存的切片体补落盘
        for u, data in list(bodies.items()):
            _save_segment(u, data)
        print(f"\n[捕获] 目标清单: {url}（{len(pl.segments)} 切片，"
              f"{'AES-128 加密' if pl.encrypted else '未加密'}）")

    def _save_segment(url, data):
        """命中期望集合的切片写盘；清单未就绪时先缓存在内存。"""
        if state["expected"] is None:
            bodies.setdefault(url, data)
            return False
        if url == state["init_url"]:
            fname = "init" + ext_from_url(url, ".mp4")
            (seg_dir / fname).write_bytes(data)
            state["init_fname"] = fname
            stat["bytes"] += len(data)
            return True
        seg = state["expected"].get(url)
        if seg is None or seg.index in saved:
            return False
        fname = f"{seg.index:06d}{ext_from_url(url)}"
        (seg_dir / fname).write_bytes(data)
        saved[seg.index] = fname
        stat["bytes"] += len(data)
        return True

    def on_response(resp):
        url = resp.url
        try:
            ct = resp.headers.get("content-type", "")
            if is_m3u8_url(url) or "mpegurl" in ct.lower():
                state["playlists"][url] = resp.text()
                state["headers"][url] = dict(resp.request.headers)
                print(f"\n[捕获] 发现清单: {url}")
                resolve_playlist()
            elif looks_like_segment(url, ct):
                data = resp.body()
                if data and len(data) > 1024:  # 过滤空响应与图标类误报
                    if _save_segment(url, data) and state["expected"]:
                        bar = render_progress(len(saved), len(state["expected"]),
                                              stat["bytes"], time.time() - state["t0"])
                        print(f"\r[捕获] {bar}", end="", flush=True)
        except DRMError as e:
            state["drm"] = state["drm"] or str(e)
            print(f"\n[失败] {e}")
        except Exception:
            pass  # 缓存受限 / 已断开等，静默跳过

    with sync_playwright() as p:
        browser = launch_browser(p, headless)
        context = browser.new_context(**context_kwargs())
        context.on("response", on_response)
        page = context.new_page()
        print(f"[播放模式] 打开页面: {page_url}")
        print("[播放模式] 保持视频播放；全部切片捕获完成自动合并，Ctrl+C 可提前结束")
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[播放模式] 页面加载警告: {e}")

        t0, last_rate = time.time(), 0.0
        try:
            while True:
                page.wait_for_timeout(1000)
                if state["drm"]:
                    raise DRMError(state["drm"])
                if speed and speed != 1.0 and time.time() - last_rate > 5:
                    _set_playback_rate(page, min(speed, 16.0))
                    last_rate = time.time()
                if state["expected"] is not None and len(saved) >= len(state["expected"]):
                    print("\n[捕获] 全部切片捕获完成")
                    break
                if page.is_closed() or not context.pages:
                    print("\n[捕获] 浏览器已关闭，停止捕获")
                    break
                if time.time() - t0 > max_wait:
                    print("\n[捕获] 达到最长等待时间，停止捕获")
                    break
        except KeyboardInterrupt:
            print("\n[捕获] 手动结束")
        state["cookies"] = context.cookies()  # 关浏览器前取出，供补拉用
        try:
            browser.close()
        except Exception:
            pass

    return _finalize_capture(state, out_dir, seg_dir, saved, insecure, proxy)


def _finalize_capture(state, out_dir, seg_dir, saved, insecure, proxy):
    """捕获结束：用继承的请求头补拉缺失切片，然后合并。"""
    if state["chosen"] is None:
        if state["drm"]:
            raise DRMError(state["drm"])
        raise RuntimeError("未捕获到 m3u8 媒体清单，播放器模式失败")
    pl = state["chosen"][1]
    missing = [s for s in pl.segments if s.index not in saved]
    need_init = state["init_url"] and not state["init_fname"]

    if missing or need_init:
        print(f"\n[补拉] 浏览器未拉取 {len(missing)} 个切片，尝试用继承请求头直接下载 ...")
        h = headers_from_request(state["headers"].get(state["chosen"][0], {}))
        session = build_session(
            referer=h.get("referer"), user_agent=h.get("user-agent"),
            cookie=h.get("cookie"), insecure=insecure, proxy=proxy,
            extra_headers={"Origin": h["origin"]} if h.get("origin") else None)
        set_cookies_from_playwright(session, state["cookies"])

        if need_init:
            try:
                data = session.get(state["init_url"], timeout=config.TIMEOUT).content
                fname = "init" + ext_from_url(state["init_url"], ".mp4")
                (seg_dir / fname).write_bytes(data)
                state["init_fname"] = fname
            except Exception as e:
                print(f"[补拉] init 段失败: {e}")

        def fetch_one(seg):
            for attempt in range(1, config.RETRY_TIMES + 1):
                try:
                    resp = session.get(seg.url, timeout=config.TIMEOUT)
                    resp.raise_for_status()
                    fname = f"{seg.index:06d}{ext_from_url(seg.url)}"
                    (seg_dir / fname).write_bytes(resp.content)
                    return seg.index, fname
                except Exception:
                    time.sleep(config.RETRY_BACKOFF * attempt)
            return None

        with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as pool:
            for r in pool.map(fetch_one, missing):
                if r:
                    saved[r[0]] = r[1]

    still_missing = sum(1 for s in pl.segments if s.index not in saved)
    if still_missing:
        print(f"[合并] 仍有 {still_missing} 个切片缺失，只合并前面连续部分")
    return finalize(out_dir, saved, init_fname=state["init_fname"])
