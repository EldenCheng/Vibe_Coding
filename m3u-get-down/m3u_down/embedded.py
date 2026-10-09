"""内嵌播放器直链解析：从播放页静态 JS 里提取「线路 × 剧集」的 m3u8 直链。

背景：部分站点（如 mvffm.net，WordPress Dooplay 主题）把全部线路与剧集的
m3u8 地址直接写进播放页的 Vue 数据里（new Vue({...videourls:[...], tables:[...]})），
打开页面即知全部直链，完全不需要浏览器嗅探。

设计：sites/ 配置的 player_embedded 字段选择解析器类型（_PARSERS 注册表分发）。
- 同结构站点（Dooplay 主题很常见）→ 只需新建 sites/*.json，零代码；
- 播放器结构真正不同的站点 → 新增一个解析函数并在 _PARSERS 注册一行。
新站点永远不需要改 CLI 参数。

详见《Design/项目设计文档.md》§13.2。
"""
import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse


# ---------- 通用工具 ----------

def _extract_json_array(text, key):
    """在文本中定位 key:[ ... ]，用括号配平取完整 JSON 数组文本（不依赖固定长度）。"""
    i = text.find(key + ":")
    if i < 0:
        return None
    start = text.find("[", i)
    if start < 0:
        return None
    depth = 0
    for j in range(start, len(text)):
        c = text[j]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    return None


def _norm_url(url):
    """URL 规范化：小写、去尾部斜杠与查询串，用于「嗅探候选 ↔ 页面直链」匹配。"""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".lower().rstrip("/")
    except Exception:
        return str(url).lower().rstrip("/")


def _norm_text(s):
    """线路名匹配用归一化：NFKC（全角/半角统一）、去空白、转小写。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"\s+", "", s).lower()


# ---------- 解析器：Dooplay 主题 Vue 播放器 ----------

def _parse_dooplay_vue(html_text, session=None, page_url=""):
    """Dooplay 主题 Vue 播放器：提取 (线路名列表, 线路×剧集直链)。

    返回 (line_names, video_urls)：
    - line_names: [str]  线路显示名（如 'FLV 22 推薦31'），下标即线路序号
    - video_urls: [[{name, url}, ...], ...]  每条线路的剧集 {集名, m3u8直链}
    解析失败返回 ((), [])，调用方容错。
    （session/page_url 参数为统一签名预留，本解析器只看页面 HTML，不用）
    """
    raw = _extract_json_array(html_text, "videourls")
    if not raw:
        return (), []
    try:
        video_urls = json.loads(raw)
    except Exception:
        return (), []
    if not isinstance(video_urls, list) or not video_urls:
        return (), []
    # 规整：每项确保是 {name, url} 字符串
    video_urls = [
        [{"name": str(e.get("name", "")), "url": str(e.get("url", ""))}
         for e in line if isinstance(e, dict)]
        for line in video_urls
    ]
    # 线路名（tables，HTML 形式）；失败或缺数时退回"线路N"
    line_names = []
    raw_t = _extract_json_array(html_text, "tables")
    if raw_t:
        try:
            tables = json.loads(raw_t)
            line_names = [
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(t.get("ht", "")))).strip()
                for t in tables if isinstance(t, dict)
            ]
        except Exception:
            pass
    if len(line_names) != len(video_urls):
        line_names = [f"线路{i + 1}" for i in range(len(video_urls))]
    return line_names, video_urls


# ---------- 解析器：ikanbot API 型（token 算法 + 一次 API 拿全部直链） ----------

def _ikanbot_token(video_id, e_token):
    """复现站点混淆 JS get_tks()：纯客户端切片算法，无需浏览器。

    取视频 ID 末 4 位数字，逐位 d：k = d % 3 + 1，从 e_token 头部取
    [k, k+8) 的 8 字符作为一段，然后 e_token = e_token[k+8:]；4 段拼接。
    """
    digits = str(video_id)[-4:]
    if not digits.isdigit():
        raise RuntimeError(f"ikanbot token 计算失败：视频 ID 末 4 位非数字（{video_id!r}）")
    b = str(e_token)
    parts = []
    for ch in digits:
        k = int(ch) % 3 + 1
        parts.append(b[k:k + 8])
        b = b[k + 8:]
    token = "".join(parts)
    if len(token) != 32:
        raise RuntimeError("ikanbot token 计算失败：e_token 长度不足（页面结构可能已变化）")
    return token


def _parse_ikanbot_api(html_text, session=None, page_url=""):
    """ikanbot（爱看机器人）：从隐藏域算 token，调 /api/getResN 拿全部直链。

    页面静态 HTML 只有 e_token/current_id/mtype 三个隐藏域；直链在 API
    响应里（data.list[].resData 为 JSON 字符串 [{flag, url}]，url 字段是
    '第01集$直链#第02集$…' 格式）。需要发一次请求，所以与 dooplay_vue
    分属不同解析器。返回结构与 dooplay_vue 相同：
    (line_names, video_urls)；解析失败返回 ((), [])。
    """
    m = re.search(r'id="e_token"\s+value="([^"]+)"', html_text)
    m_id = re.search(r'id="current_id"\s+value="([^"]+)"', html_text)
    m_type = re.search(r'id="mtype"\s+value="([^"]+)"', html_text)
    if not (m and m_id):
        return (), []
    token = _ikanbot_token(m_id.group(1), m.group(1))
    api = urljoin(page_url or "https://www1.ikanbot.com/", "/api/getResN")
    params = {"videoId": m_id.group(1), "mtype": (m_type.group(1) if m_type else ""),
              "token": token}
    # sniff 标注场景没有现成 session，退化为裸 requests（失败只影响标注）
    if session is None:
        import requests
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0"
    resp = session.get(api, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("state") != 1:
        raise RuntimeError(f"ikanbot API 返回异常 state={data.get('state')} "
                           f"（token 失效或页面结构变化）")
    line_names, video_urls = [], []
    for i, item in enumerate(data.get("data", {}).get("list") or []):
        try:
            arr = json.loads(item.get("resData") or "[]")
        except Exception:
            arr = []
        # 线路名：线路N (flag)，flag 如 gsm3u8/lzm3u8，便于辨认资源站
        flags = [str(r.get("flag")).strip() for r in arr if r.get("flag")]
        line_names.append(f"线路{i + 1}" + (f" ({', '.join(flags)})" if flags else ""))
        eps = []
        for r in arr:
            for piece in str(r.get("url") or "").split("#"):
                if "$" not in piece:
                    continue
                name, link = piece.split("$", 1)
                name = re.sub(r"^第(\d+)([集話话])$",
                              lambda mm: f"第{int(mm.group(1)):02d}{mm.group(2)}",
                              name.strip())   # 部分线路不补零，归一化避免排序混乱
                if link.strip():
                    eps.append({"name": name, "url": link.strip()})
        video_urls.append(eps)
    if not video_urls:
        return (), []
    return line_names, video_urls


# ---------- 解析器注册表 ----------

_PARSERS = {
    "dooplay_vue": _parse_dooplay_vue,
    "ikanbot_api": _parse_ikanbot_api,
}


def parse(html_text, kind, session=None, page_url=""):
    """按 kind 分发到注册的解析器；未知类型明确报错（提示可用值）。

    session/page_url 供需要发请求的解析器使用（如 ikanbot_api）；
    纯页面解析器忽略这两个参数。
    """
    fn = _PARSERS.get(kind)
    if fn is None:
        raise RuntimeError(
            f"未知的内嵌播放器解析器: {kind}（sites 配置 player_embedded "
            f"目前支持: {', '.join(sorted(_PARSERS)) or '无'}）")
    return fn(html_text, session=session, page_url=page_url)


def line_match(line_names, spec):
    """把 --line 参数匹配到线路下标（0 基）；匹配不到返回 None。

    spec 支持（依次尝试）：
    1. 纯数字 → 1 基序号（22 → 第 22 条）
    2. 线路名精确匹配（去空白/大小写/NFKC 归一化后）
    3. FLV 序号匹配：spec 里提取 FLV\\s*(\\d+) 与线路名比对（繁简差异也能命中）
    4. spec 里仅含一个数字且是合法序号 → 按 1 基序号
    """
    if spec is None:
        return None
    spec = str(spec).strip()
    if not spec:
        return None
    n = len(line_names)
    if spec.isdigit():
        i = int(spec)
        return i - 1 if 1 <= i <= n else None
    want = _norm_text(spec)
    for i, name in enumerate(line_names):
        if _norm_text(name) == want:
            return i
    m = re.search(r"flv\s*(\d+)", want)
    if m:
        want_no = int(m.group(1))
        for i, name in enumerate(line_names):
            nm = re.search(r"flv\s*(\d+)", _norm_text(name))
            if nm and int(nm.group(1)) == want_no:
                return i
    nums = re.findall(r"\d+", spec)
    if len(nums) == 1 and 1 <= int(nums[0]) <= n:
        return int(nums[0]) - 1
    return None


def url_label_map(video_urls, line_names):
    """直链 URL → (线路名, 集名) 映射（供 sniff 候选标注；规范化 URL 作键）。"""
    out = {}
    for i, line in enumerate(video_urls):
        name = line_names[i] if i < len(line_names) else f"线路{i + 1}"
        for ep in line:
            u = ep.get("url") or ""
            if u:
                out.setdefault(_norm_url(u), (name, str(ep.get("name") or "")))
    return out
