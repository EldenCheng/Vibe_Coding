"""有头浏览器嗅探播放页中的 m3u8 清单地址。

线程模型：Playwright 事件循环跑在子线程，主线程负责终端交互——
主线程若阻塞在 input()，浏览器事件会停止分发、候选列表无法实时刷新，
因此拆线程 + queue 通信。

v0.4.0：页面池 + 弹窗跟踪。部分站点点击播放后会把原页面跳转到广告页，
真视频在自动新开的窗口里播放。context 级 response 监听本就能捕获弹窗里的
m3u8，但旧实现只盯主页面：主页面（广告页）一关闭循环就中断、嗅探提前退出。
现在跟踪全部存活页面，任一页面存活就继续等候选，并提示跳转/新窗口；
内嵌播放器站点（sites 配置 player_embedded）的候选还会标注线路名/集名。
"""
import queue
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from . import config, sites
from .embedded import parse as parse_embedded, url_label_map
from .session import headers_from_request, probe_proxy
from .utils import is_m3u8_url


@dataclass
class SniffResult:
    url: str          # 选中的 m3u8 地址
    headers: dict     # 可继承的浏览器请求头（小写键）
    cookies: list     # Playwright context.cookies()
    title: str = ""


def launch_browser(playwright, headless=False):
    """chromium 优先；未安装内核时回退本机 Edge / Chrome 通道。"""
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception:
        pass
    for channel in ("msedge", "chrome"):
        try:
            return playwright.chromium.launch(headless=headless, channel=channel)
        except Exception:
            continue
    raise RuntimeError("未找到可用浏览器内核：请先执行 py -m playwright install chromium，"
                       "或确认本机已安装 Edge/Chrome")


def context_kwargs(probe_url=None, direct_first=False):
    """Playwright context 代理选项（config.proxy 非空时启用，与 requests 同源）。

    probe_url 传入目标页 URL 时先探测哪个出口能连通目标站点（requests
    各发一次请求）；浏览器无法像 requests 那样逐请求降级，只能在启动前取舍：
    - direct_first=False（推荐代理）：代理不通则直连打开；
    - direct_first=True（不推荐代理）：直连不通才用代理打开。
    """
    if not config.PROXY:
        return {}
    if probe_url is not None:
        route = probe_proxy(probe_url, direct_first=direct_first)
        if route == "proxy":
            return {"proxy": {"server": config.PROXY}}
        if direct_first:
            print(f"[网络] 直连不通，浏览器改用代理 {config.PROXY}")
        else:
            print(f"[代理] {config.PROXY} 无法连通目标站点，浏览器改用直连")
        return {}
    return {"proxy": {"server": config.PROXY}}


def _is_m3u8_response(url, content_type):
    return is_m3u8_url(url) or "mpegurl" in (content_type or "").lower()


def sniff(page_url, auto=None, headless=False, max_wait=1800):
    """打开播放页监听网络，返回用户选中（或 --auto 指定）的 m3u8 及会话信息。

    auto：非交互模式——出现第 N 个候选时自动选择（脚本化测试用）。

    v0.4.0：跟踪自动新开的窗口（弹窗）与主页面跳转——
    主页面跳广告页被关闭后，只要弹窗还在播就继续等候选。
    """
    events = queue.Queue()    # worker -> 主线程：候选 / 标题 / 结果 / 异常 / 页面事件
    commands = queue.Queue()  # 主线程 -> worker：pick / quit
    candidates = {}           # url -> 浏览器请求头（dict 保持发现顺序）
    title_holder = [""]
    origin_host = (urlparse(page_url).netloc or "").split(":")[0]

    def worker():
        try:
            with sync_playwright() as p:
                # 站点配置：浏览器出口策略 + 内嵌直链候选标注共用
                site_cfg = sites.match(page_url)
                df = bool(site_cfg and site_cfg.proxy_policy == "direct_first")
                browser = launch_browser(p, headless)
                context = browser.new_context(**context_kwargs(probe_url=page_url,
                                                               direct_first=df))
                live = []      # 存活页面池（主页面 + 弹窗）
                announced = {page_url}   # 已提示过的跳转 URL，避免刷屏
                url_labels = {}   # 内嵌播放器站点：直链 → (线路名, 集名)，候选标注用

                def on_response(resp):
                    try:
                        ct = resp.headers.get("content-type", "")
                        if _is_m3u8_response(resp.url, ct) and resp.url not in candidates:
                            candidates[resp.url] = dict(resp.request.headers)
                            lbl = url_labels.get(_norm_url(resp.url))
                            events.put(("candidate", (resp.url, lbl)))
                    except Exception:
                        pass

                context.on("response", on_response)

                def track_page(pg, is_main):
                    """把页面纳入存活池，挂关闭/跳转监听（幂等）。"""
                    if pg in live:
                        return
                    live.append(pg)

                    def on_close():
                        if pg in live:
                            live.remove(pg)
                        events.put(("page_closed", (pg.url, is_main, bool(live))))

                    def on_nav(frame):
                        if frame == pg.main_frame and frame.url not in announced:
                            announced.add(frame.url)
                            events.put(("page_nav", frame.url))

                    try:
                        pg.on("close", on_close)
                        pg.on("framenavigated", on_nav)
                    except Exception:
                        pass
                    events.put(("page_open", (pg.url, is_main)))

                page = context.new_page()
                track_page(page, True)
                context.on("page", lambda pg: track_page(pg, False))

                print(f"[嗅探] 正在打开页面: {page_url}")
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    print(f"[嗅探] 页面加载警告: {e}")
                try:
                    title_holder[0] = page.title()
                except Exception:
                    pass
                events.put(("title", title_holder[0]))

                # 内嵌播放器站点：从页面 JS 提取 直链→(线路名, 集名)，标注候选。
                # 页面已跳广告页时解析失败也没关系，标注退化为空。
                try:
                    if site_cfg and site_cfg.player_embedded:
                        line_names, video_urls = parse_embedded(page.content(),
                                                                site_cfg.player_embedded)
                        url_labels = url_label_map(video_urls, line_names)
                except Exception:
                    pass

                while True:
                    # 先处理主线程指令，再让 Playwright 分发 200ms 网络事件
                    try:
                        cmd = commands.get_nowait()
                    except queue.Empty:
                        cmd = None
                    if cmd:
                        if cmd[0] == "pick":
                            events.put(("result", SniffResult(
                                url=cmd[1],
                                headers=headers_from_request(candidates[cmd[1]]),
                                cookies=context.cookies(),
                                title=title_holder[0],
                            )))
                            break
                        if cmd[0] == "quit":
                            events.put(("result", None))
                            break
                    # 等待：对页面池中任一存活页面 tick；全部关闭才结束——
                    # 广告页跳转后主页面被关闭不再中断，弹窗还在播就继续等候选
                    waited = False
                    for pg in list(live):
                        try:
                            pg.wait_for_timeout(200)
                            waited = True
                            break
                        except Exception:
                            if pg in live:
                                live.remove(pg)
                            events.put(("page_closed", (pg.url, False, bool(live))))
                    if not waited:
                        events.put(("closed", None))
                        break

                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            events.put(("error", str(e)))

    threading.Thread(target=worker, daemon=True).start()

    if auto is None:
        def input_loop():
            while True:
                try:
                    line = input()
                except (EOFError, OSError):
                    return
                line = line.strip()
                if line:
                    commands.put(("input", line))
                if line == "q":
                    return
        threading.Thread(target=input_loop, daemon=True).start()
        print("[嗅探] 在浏览器中操作页面触发播放；输入编号选择候选，r 刷新，q 退出")
        print("[嗅探] 若页面跳转到广告页或自动打开新窗口，请在新窗口点击播放，候选会自动捕获")

    picked, pick_sent, closed = None, False, False
    t0 = time.time()
    try:
        while time.time() - t0 < max_wait:
            try:
                ev = events.get(timeout=0.5)
            except queue.Empty:
                ev = None
            if ev:
                kind, payload = ev[0], ev[-1]
                if kind == "candidate":
                    url, lbl = payload
                    idx = len(candidates)
                    if lbl:
                        print(f"  [{idx}] {url}  （线路: {lbl[0]} · {lbl[1]}）")
                    else:
                        print(f"  [{idx}] {url}")
                elif kind == "title":
                    if payload:
                        print(f"[嗅探] 页面标题: {payload}")
                elif kind == "page_open":
                    u, is_main = payload
                    if not is_main:
                        print(f"[嗅探] 检测到新窗口: {u}（真视频可能在此播放）")
                elif kind == "page_nav":
                    u = payload
                    print(f"[嗅探] 页面跳转: {u}")
                    if urlparse(u).netloc.split(":")[0] != origin_host:
                        print("[嗅探] 已离开原站点（可能是广告页）；"
                              "真视频若在自动新开的窗口中播放，候选会自动捕获")
                elif kind == "page_closed":
                    u, is_main, still_alive = payload
                    if is_main and still_alive:
                        print("[嗅探] 原页面已关闭；仍在监听新窗口的播放请求，请在新窗口操作")
                elif kind == "input":
                    line = payload
                    if line == "q":
                        commands.put(("quit",))
                    elif line == "r":
                        for i, u in enumerate(candidates, 1):
                            print(f"  [{i}] {u}")
                    elif line.isdigit():
                        i = int(line)
                        urls = list(candidates)
                        if 1 <= i <= len(urls):
                            commands.put(("pick", urls[i - 1]))
                            pick_sent = True
                        else:
                            print(f"  编号超出范围（当前 1~{len(urls)}）")
                elif kind == "result":
                    picked = payload
                    break
                elif kind == "closed":
                    closed = True
                    break
                elif kind == "error":
                    raise RuntimeError(f"嗅探线程异常: {payload}")
            # 非交互自动选择（测试 / 脚本用）
            if auto is not None and not pick_sent and len(candidates) >= auto:
                commands.put(("pick", list(candidates)[auto - 1]))
                pick_sent = True
    except KeyboardInterrupt:
        commands.put(("quit",))

    if picked is None and closed and candidates and auto is None:
        # 浏览器全部关闭但已有候选：退化为纯终端选择
        for i, u in enumerate(candidates, 1):
            print(f"  [{i}] {u}")
        idx = input("浏览器已关闭，输入编号选择要下载的清单: ").strip()
        if idx.isdigit() and 1 <= int(idx) <= len(candidates):
            url = list(candidates)[int(idx) - 1]
            picked = SniffResult(url=url,
                                 headers=headers_from_request(candidates[url]),
                                 cookies=[], title=title_holder[0])
    if picked is None:
        raise RuntimeError("未能捕获/选择到 m3u8（可尝试先在页面里手动点击播放）")
    return picked


def _norm_url(url):
    """候选 URL 规范化（与 embedded 模块保持一致），用于标注查找。"""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".lower().rstrip("/")
    except Exception:
        return str(url).lower().rstrip("/")
