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


# 出口降级提示只打一次（batch 每集都新建会话，不限制会刷屏）
_route_warned = [False]


class ProxyOrderSession(requests.Session):
    """按出口顺序表降级的会话：当前出口连接层失败时切到下一档并粘住。

    steps 形如 [(proxies_dict, 名称), ...]：
    - 推荐代理：[(代理, '代理 http://..'), ({}, '直连')]
    - 不推荐代理：[({}, '直连'), (代理, '代理 http://..')]
    连接层失败判定为 requests.exceptions.ConnectionError（含 ProxyError、
    ConnectTimeout、SSL 错误）；读超时不算（站点响应慢≠出口不可达，降级无益）。
    切换后本会话粘住新出口；batch 每集新建会话仍从头尝试——代理恢复后自动回到优先出口。
    """

    def __init__(self, steps, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._steps = steps or [({}, "直连")]
        self._step = 0
        self.trust_env = False   # 出口完全由顺序表决定，不读系统/环境代理
        self.proxies = dict(self._steps[0][0])

    def send(self, request, **kwargs):
        # request() 会把预合并的代理 dict 塞进 kwargs 并覆盖 self.proxies，必须去掉
        kwargs.pop("proxies", None)
        while True:
            try:
                return super().send(request, **kwargs)
            except requests.exceptions.ConnectionError:
                if self._step + 1 < len(self._steps):
                    prev = self._steps[self._step][1]
                    self._step += 1
                    self.proxies = dict(self._steps[self._step][0])
                    if not _route_warned[0]:
                        _route_warned[0] = True
                        print(f"[网络] {prev}失败，改用{self._steps[self._step][1]}"
                              f"（出口恢复后重跑命令即可切回）")
                    continue
                raise


def probe_proxy(url, direct_first=False, insecure=None):
    """探测代理/直连哪个能连通目标站点（浏览器启动前决定出口）。

    浏览器无法逐请求降级，只能在启动前取舍。返回可用出口 'proxy' / 'direct'；
    未配置代理返回 None（浏览器只能直连）。
    direct_first=False（推荐代理）：先试代理，连接层失败再试直连；
    direct_first=True（不推荐代理）：先试直连，失败再试代理；
    两条都不通时返回直连（让页面加载自己报错，与旧行为一致）。
    判定：任何 HTTP 响应（含 403/跳转）即出口可用；ConnectionError 为不通；
    读超时等说明 TCP 已通、出口本身可用。
    """
    proxy = config.PROXY
    if not proxy:
        return None
    P = {"http": proxy, "https": proxy}
    verify = not (config.INSECURE if insecure is None else insecure)
    order = ([("direct", None), ("proxy", P)] if direct_first
             else [("proxy", P), ("direct", None)])
    for name, px in order:
        try:
            s = requests.Session()
            s.trust_env = False   # 直连探测必须屏蔽系统/环境代理
            resp = s.get(url, headers={"User-Agent": DEFAULT_UA}, proxies=px,
                         timeout=(3, 8), stream=True, allow_redirects=False,
                         verify=verify)
            resp.close()
            return name
        except requests.exceptions.ConnectionError:
            continue
        except requests.exceptions.RequestException:
            return name
    return "direct"


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
                  insecure=None, extra_headers=None, proxy=None,
                  direct_first=False):
    """构造下载用 requests 会话。

    referer / user_agent / cookie：手动指定的请求头（CLI --referer 等）
    insecure / proxy：None 表示回落到 config.json 配置
    配置了代理时会话具备出口降级能力：direct_first=False 先代理后直连
    （推荐代理，默认）；True 先直连后代理（不推荐代理）。
    显式传入 proxy（CLI --proxy）视为用户明确意图，忽略 direct_first。
    """
    _proxy = config.PROXY if proxy is None else proxy
    if proxy is not None:
        direct_first = False
    if not _proxy:
        s = requests.Session()
    else:
        P = {"http": _proxy, "https": _proxy}
        steps = ([({}, "直连"), (P, f"代理 {_proxy}")] if direct_first
                 else [(P, f"代理 {_proxy}"), ({}, "直连")])
        s = ProxyOrderSession(steps)
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


def session_from_sniff(sniff_result, insecure=None, proxy=None,
                       direct_first=False):
    """用嗅探结果（继承请求头 + 浏览器 cookies）构造下载会话。"""
    h = sniff_result.headers
    s = build_session(
        referer=h.get("referer"),
        user_agent=h.get("user-agent"),
        cookie=h.get("cookie"),
        insecure=insecure,
        proxy=proxy,
        direct_first=direct_first,
        extra_headers={"Origin": h["origin"]} if h.get("origin") else None,
    )
    # 浏览器 context 的 cookie 更完整（含 HttpOnly 等），单独灌入
    set_cookies_from_playwright(s, sniff_result.cookies)
    return s
