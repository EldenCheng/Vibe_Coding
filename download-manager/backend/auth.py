"""访问令牌校验与 IP 白名单。

只做「一个人的管理器」所需的保护：一个长随机令牌，前端存 localStorage 长期有效。
局域网内任何设备只要没有令牌就打不开页面、调不动接口。

允许三种携带方式（按顺序检查）：
1. 请求头 X-Auth-Token
2. 请求头 Authorization: Bearer <token>
3. 查询参数 ?token=<token>（仅用于首次进入页面，前端读到后存起来并从地址栏移除）
"""
import ipaddress
import secrets

from . import config as manager_config
from .httpd import Response

# 这些路径不需要令牌：否则首次进入页面时连 HTML 都拿不到，无法展示引导页。
# 注意：/ 与 /index.html（前端页面本身）**需要**令牌，未授权时由前端展示引导页。
PUBLIC_PATHS = ("/api/health", "/login", "/favicon.ico")


def extract_token(req):
    token = req.header("x-auth-token").strip()
    if token:
        return token
    auth = req.header("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (req.arg("token") or "").strip()


def token_ok(expected, provided):
    """常数时间比较，避免时序攻击推断令牌。"""
    if not expected or not provided:
        return False
    return secrets.compare_digest(str(expected), str(provided))


def ip_allowed(cfg, ip):
    """按 allowed_cidrs 判断来源 IP；列表为空表示不启用白名单。"""
    allowed = (cfg.get("server", {}) or {}).get("allowed_cidrs") or []
    if not allowed:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for item in allowed:
        try:
            if addr in ipaddress.ip_network(str(item), strict=False):
                return True
        except ValueError:
            continue
    return False


def is_public(path):
    return path in PUBLIC_PATHS


def check_request(req):
    """返回 None 表示放行，否则返回 Response（403/401）。"""
    cfg = manager_config.get_config()
    if not ip_allowed(cfg, req.remote):
        return Response.error(f"来源 IP {req.remote} 不在允许的网段内", 403, "ip_forbidden")
    if is_public(req.path):
        return None
    expected = (cfg.get("server", {}) or {}).get("access_token", "")
    if token_ok(expected, extract_token(req)):
        return None
    return Response.error("缺少或无效的访问令牌", 401, "unauthorized")
