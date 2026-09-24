"""requests 会话构造与浏览器请求头继承。

背景：多数"版权限制不能下载"实为服务器校验 Referer/UA/Cookie，
带上浏览器的请求头即可直接下载，请求头继承是本工具的隐形主力。
"""
import warnings

import requests

from . import config

# 默认 UA：不带 UA 的请求很多 CDN 直接拒绝
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 下载时值得从浏览器会话继承的请求头（小写）
_INHERIT_KEYS = ("user-agent", "referer", "origin", "cookie")


def parse_cookie_string(cookie_str):
    """解析 'k=v; k2=v2' 形式的 Cookie 字符串为字典。"""
    out = {}
    for part in (cookie_str or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def build_session(referer=None, user_agent=None, cookie=None,
                  insecure=None, extra_headers=None, proxy=None):
    """构造下载用 requests 会话。

    referer / user_agent / cookie：手动指定的请求头（CLI --referer 等）
    insecure / proxy：None 表示回落到 config.json 配置
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": user_agent or DEFAULT_UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })
    if referer:
        s.headers["Referer"] = referer
    if cookie:
        for k, v in parse_cookie_string(cookie).items():
            s.cookies.set(k, v)
    if extra_headers:
        s.headers.update(extra_headers)
    if insecure if insecure is not None else config.INSECURE:
        s.verify = False
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    proxy = config.PROXY if proxy is None else proxy
    if proxy:
        # 与 Playwright 浏览器使用同一代理，保证嗅探/下载出口一致
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def headers_from_request(req_headers):
    """从浏览器请求头（Playwright request.headers）里挑选可继承的字段。"""
    low = {k.lower(): v for k, v in (req_headers or {}).items()}
    return {k: low[k] for k in _INHERIT_KEYS if low.get(k)}


def set_cookies_from_playwright(session, cookies):
    """把 Playwright context.cookies() 灌入 requests 会话。"""
    for c in cookies or []:
        try:
            session.cookies.set(c.get("name"), c.get("value"),
                                domain=c.get("domain"), path=c.get("path", "/"))
        except Exception:
            pass  # 个别异常 cookie 跳过，不影响整体


def session_from_sniff(sniff_result, insecure=None, proxy=None):
    """用嗅探结果（继承请求头 + 浏览器 cookies）构造下载会话。"""
    h = sniff_result.headers
    s = build_session(
        referer=h.get("referer"),
        user_agent=h.get("user-agent"),
        cookie=h.get("cookie"),
        insecure=insecure,
        proxy=proxy,
        extra_headers={"Origin": h["origin"]} if h.get("origin") else None,
    )
    # 浏览器 context 的 cookie 更完整（含 HttpOnly 等），单独灌入
    set_cookies_from_playwright(s, sniff_result.cookies)
    return s
