"""有头浏览器嗅探播放页中的 m3u8 清单地址。

线程模型：Playwright 事件循环跑在子线程，主线程负责终端交互——
主线程若阻塞在 input()，浏览器事件会停止分发、候选列表无法实时刷新，
因此拆线程 + queue 通信。
"""
import queue
import threading
import time
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

from . import config
from .session import headers_from_request
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


def context_kwargs():
    """Playwright context 代理选项（config.proxy 非空时启用，与 requests 同源）。"""
    return {"proxy": {"server": config.PROXY}} if config.PROXY else {}


def _is_m3u8_response(url, content_type):
    return is_m3u8_url(url) or "mpegurl" in (content_type or "").lower()


def sniff(page_url, auto=None, headless=False, max_wait=1800):
    """打开播放页监听网络，返回用户选中（或 --auto 指定）的 m3u8 及会话信息。

    auto：非交互模式——出现第 N 个候选时自动选择（脚本化测试用）。
    """
    events = queue.Queue()    # worker -> 主线程：候选 / 标题 / 结果 / 异常
    commands = queue.Queue()  # 主线程 -> worker：pick / quit
    candidates = {}           # url -> 浏览器请求头（dict 保持发现顺序）
    title_holder = [""]

    def worker():
        try:
            with sync_playwright() as p:
                browser = launch_browser(p, headless)
                context = browser.new_context(**context_kwargs())

                def on_response(resp):
                    try:
                        ct = resp.headers.get("content-type", "")
                        if _is_m3u8_response(resp.url, ct) and resp.url not in candidates:
                            candidates[resp.url] = dict(resp.request.headers)
                            events.put(("candidate", resp.url))
                    except Exception:
                        pass

                context.on("response", on_response)
                page = context.new_page()
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
                    try:
                        page.wait_for_timeout(200)
                    except Exception:
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
                    print(f"  [{len(candidates)}] {payload}")
                elif kind == "title":
                    if payload:
                        print(f"[嗅探] 页面标题: {payload}")
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
        # 浏览器被手动关闭但已有候选：退化为纯终端选择
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
