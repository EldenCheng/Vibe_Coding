"""
E-Hentai 画廊图片下载脚本
=========================
用法:
  py download_gallery.py <画廊URL>                    下载全部 / 断点续传
  py download_gallery.py --range 1-10,20,30-40 <URL>  只下载指定页码范围
  py download_gallery.py --rd <URL>                   重试 progress.json 中 failed 页
  py download_gallery.py --check <URL>                按 images/ 实际文件校正进度

说明:
  - 只下载网页显示的图片（非原图），图片统一命名 {页码:04d}_{网页显示名}
  - 单线程下载，每页随机等待（默认 3~5 秒），进度即时落盘支持续传
  - 页面列表优先取 MPV API，失败回退画廊页缩略图解析
"""

import sys
import json
import re
import time
import random
import html as html_lib
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from tag_translations import GROUP_PREFIX_TRANSLATIONS, TAG_TRANSLATIONS


# 脚本所在目录
BASE_DIR = Path(__file__).parent
# 全局配置文件路径
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    """加载 config.json 中的全局配置，缺失的字段用内置默认值补全"""
    defaults = {
        "proxy": "",
        "use_mpv": False,
        "request_delay": {"min": 3, "max": 5},
        "retry": {"max_attempts": 3, "backoff_base": 30, "backoff_multiplier": 2},
        "timeout_page": 30,
        "timeout_image": 120,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Referer": "https://e-hentai.org/",
        },
        "cookies": {},
    }
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_config = json.load(f)
        # 用户配置覆盖默认值（仅对已有字段进行覆盖）
        for key in defaults:
            if key in user_config:
                if isinstance(defaults[key], dict):
                    defaults[key].update(user_config[key])
                else:
                    defaults[key] = user_config[key]
    return defaults


def create_session(config):
    """创建 requests.Session：设置请求头、可选登录 Cookie、可选代理"""
    session = requests.Session()
    session.headers.update(config["headers"])

    # 注入配置中的 Cookie（如登录态的 ipb_member_id / ipb_pass_hash）
    cookies = {k: v for k, v in config.get("cookies", {}).items() if v}
    if cookies:
        session.cookies.update(cookies)

    # 配置代理（仅支持 http/https 代理）
    proxy = (config.get("proxy") or "").strip()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def parse_gallery_url(url):
    """
    解析画廊 URL，返回 (base, gid, token)
    支持形如 https://e-hentai.org/g/3743290/8eee725d8c/ 的地址
    """
    m = re.search(r"^(https?://[^/]+)/g/(\d+)/([0-9a-f]+)/?", url)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), m.group(3)


def fetch_gallery_info(session, config, base, gid, token):
    """
    获取画廊页信息，返回 (info, error)
      info 字段: title/subtitle/category/uploader/posted/language/
                 file_size/length/favorited/rating/tags
        tags 为 [(分组, [标签...]), ...] 有序列表（保留网页分组顺序）
      - error 为 None：成功
      - error = "not_available"：画廊返回 404（已删除，或仅登录用户可见）
      - error = "network"：网络/服务器错误
    """
    gallery_url = f"{base}/g/{gid}/{token}/"
    retry_cfg = config["retry"]
    for attempt in range(1, retry_cfg["max_attempts"] + 1):
        try:
            resp = session.get(gallery_url, timeout=config["timeout_page"])
            text = resp.text or ""
            # 画廊被删除或仅登录用户可见时，站点统一返回 404 "Gallery Not Available"
            if resp.status_code == 404 or "gallery not available" in text.lower() \
                    or "has been removed or is unavailable" in text.lower():
                return None, "not_available"
            # 内容警告页：自动以 ?nw=session 确认（响应即真实画廊页，服务器同时下发会话 Cookie）
            if resp.status_code == 200 and ("content warning" in text.lower() or "nw=session" in text):
                print("  [内容警告] 画廊需要确认，自动以 nw=session 跳过...")
                try:
                    resp = session.get(gallery_url + "?nw=session", timeout=config["timeout_page"])
                    text = resp.text or ""
                except requests.RequestException as e:
                    print(f"  [内容警告确认失败] {e}")
            if resp.status_code == 200 and text:
                soup = BeautifulSoup(text, "lxml")
                info = {
                    "title": "",
                    "subtitle": "",
                    "category": "",
                    "uploader": "",
                    "posted": "",
                    "language": "",
                    "file_size": "",
                    "length": "",
                    "favorited": "",
                    "rating": "",
                    "tags": [],
                }
                # 主标题 <h1 id="gn">、副标题 <h1 id="gj">
                info["title"] = soup.select_one("#gn").get_text(strip=True) if soup.select_one("#gn") else ""
                info["subtitle"] = soup.select_one("#gj").get_text(strip=True) if soup.select_one("#gj") else ""
                # 分类、上传者
                info["category"] = soup.select_one("#gdc").get_text(" ", strip=True) if soup.select_one("#gdc") else ""
                info["uploader"] = soup.select_one("#gdn").get_text(strip=True) if soup.select_one("#gdn") else ""
                # 信息表 #gdd: Posted/Visible/Language/File Size/Length/Favorited
                if soup.select_one("#gdd"):
                    for tr in soup.select("#gdd tr"):
                        cells = tr.find_all("td")
                        if len(cells) < 2:
                            continue
                        key = cells[0].get_text(strip=True)
                        value = cells[1].get_text(" ", strip=True)
                        if key == "Posted:":
                            info["posted"] = value
                        elif key == "Language:":
                            info["language"] = value
                        elif key == "File Size:":
                            info["file_size"] = value
                        elif key == "Length:":
                            info["length"] = value
                        elif key == "Favorited:":
                            info["favorited"] = value
                # 评分 #rating_label（"Average: 4.66" → 4.66）
                if soup.select_one("#rating_label"):
                    info["rating"] = soup.select_one("#rating_label").get_text(strip=True).replace("Average:", "").strip()
                # 标签分组 #taglist：每行 <td class="tc">前缀</td><td>标签们</td>
                for tr in soup.select("#taglist tr"):
                    tds = tr.find_all("td")
                    if len(tds) < 2:
                        continue
                    prefix = tds[0].get_text(strip=True).rstrip(":")
                    tags = [a.get_text(strip=True) for a in tds[1].find_all("a")]
                    if prefix and tags:
                        info["tags"].append((prefix, tags))
                return info, None
        except requests.RequestException as e:
            print(f"  [画廊页获取失败 {attempt}] {e}")
        if attempt < retry_cfg["max_attempts"]:
            time.sleep(retry_cfg["backoff_base"] * (retry_cfg["backoff_multiplier"] ** (attempt - 1)))
    return None, "network"


def fetch_page_list_mpv(session, config, base, gid, token):
    """
    方式A：MPV API 获取全部页面信息
    GET {base}/mpv/{gid}/{token}/ → JSON {imagelist: [{k, p, nl}, ...]}
    返回 [{key, page, nl}] 列表，失败返回 None
    """
    mpv_url = f"{base}/mpv/{gid}/{token}/"
    try:
        resp = session.get(mpv_url, timeout=config["timeout_page"])
        if resp.status_code != 200:
            return None
        data = resp.json()
        imagelist = data.get("imagelist")
        if not isinstance(imagelist, list) or not imagelist:
            return None
        page_infos = []
        for idx, item in enumerate(imagelist):
            key = item.get("k")
            if not key:
                continue
            page = item.get("p") or (idx + 1)  # p 字段缺失时按列表顺序补页码
            page_infos.append({"key": str(key), "page": int(page), "nl": item.get("nl")})
        return page_infos or None
    except (requests.RequestException, ValueError):
        return None


def fetch_page_list_gdt(session, config, base, gid, token, gallery_html):
    """
    方式B（回退）：解析画廊页 #gdt 缩略图链接，并按 ?p= 翻页收集全部页面
    gallery_html 为已抓取的第一页 HTML，避免重复请求
    返回 [{key, page, nl}] 列表，失败返回 None
    """
    def parse_gdt(html_text):
        """从一页画廊 HTML 中提取所有 /s/{key}/{gid}-{page} 链接"""
        found = []
        soup = BeautifulSoup(html_text, "lxml")
        for a in soup.select("#gdt a"):
            href = a.get("href", "")
            m = re.search(r"/s/(\w+)/(\d+)-(\d+)", href)
            if m:
                found.append({"key": m.group(1), "page": int(m.group(3)), "nl": None})
        return found

    page_infos = parse_gdt(gallery_html)
    seen_keys = {p["key"] for p in page_infos}
    gallery_url = f"{base}/g/{gid}/{token}/"

    # 画廊缩略图每页约 40 张，逐页翻页直到无新增（上限 200 页保护）
    for n in range(1, 201):
        try:
            resp = session.get(gallery_url, params={"p": n}, timeout=config["timeout_page"])
            if resp.status_code != 200 or not resp.text:
                break
            batch = parse_gdt(resp.text)
            new_batch = [p for p in batch if p["key"] not in seen_keys]
            if not new_batch:
                break  # 无新页面说明已翻完
            for p in new_batch:
                seen_keys.add(p["key"])
            page_infos.extend(new_batch)
            time.sleep(random.uniform(1, 2))  # 翻页间短暂延迟
        except requests.RequestException:
            break
    return page_infos or None


def get_page_html_with_retry(session, config, url):
    """
    带重试的查看页 HTML 获取（指数退避）
    检测 IP 封禁提示时额外加长等待
    返回 HTML 文本，失败返回 None
    """
    retry_cfg = config["retry"]
    for attempt in range(1, retry_cfg["max_attempts"] + 1):
        try:
            resp = session.get(url, timeout=config["timeout_page"])
            if resp.status_code == 200 and resp.text:
                text = resp.text
                if "temporarily banned" in text.lower() or "ip address has been banned" in text.lower():
                    # 触发站点限流：加长等待后重试
                    wait = 60 * attempt
                    print(f"    [限流警告] 页面被临时限制，等待 {wait}s 后重试 ({attempt}/{retry_cfg['max_attempts']})")
                    time.sleep(wait)
                    continue
                return text
            print(f"    [页面 {attempt}/{retry_cfg['max_attempts']}] HTTP {resp.status_code}")
        except requests.RequestException as e:
            print(f"    [页面 {attempt}/{retry_cfg['max_attempts']}] {e}")
        if attempt < retry_cfg["max_attempts"]:
            wait = retry_cfg["backoff_base"] * (retry_cfg["backoff_multiplier"] ** (attempt - 1))
            print(f"    等待 {wait}s 后重试...")
            time.sleep(wait)
    return None


def parse_view_page(page_html, page_url):
    """
    解析单页查看页 HTML（正则移植自油猴脚本 e-hentail-downloader.js）
    返回 (img_url, shown_name, next_nl)
    """
    # 1. 网页显示的图片地址（非原图），相对路径转绝对
    img_url = None
    m = re.search(r'<img id="img" src="(\S+?)"', page_html)
    if not m:
        # 部分页面 preview 图没有 id="img"
        m = re.search(r"</(?:script|iframe)><a[\s\S]+?><img src=\"(\S+?)\"", page_html)
    if m:
        img_url = urljoin(page_url, html_lib.unescape(m.group(1)))

    # 2. 网页显示的文件名（油猴同款正则 + 宽松备选）
    shown_name = ""
    m = re.search(r'g/l\.png"\s?/></a></div><div>([\s\S]+?) :: ', page_html)
    if not m:
        m = re.search(r"<div[^>]*>([^<>]{1,200}?) :: \d+x\d+", page_html)
    if m:
        shown_name = html_lib.unescape(m.group(1)).strip()

    # 3. 下一页的 nl 预载令牌
    next_nl = None
    m = re.search(r"return nl\('([\d\w-]+)'\)", page_html)
    if m:
        next_nl = m.group(1)

    return img_url, shown_name, next_nl


def sanitize_filename(name):
    """清理文件名：非法字符替换为空格，合并连续空白"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip().strip(".")
    return name


def build_base_name(title, subtitle, max_title_len=40, max_total_len=100):
    """目录名主体：主标题[+副标题]（不含分类/语言前缀）"""
    name = sanitize_filename(title)
    if not name:
        return ""
    sub = sanitize_filename(subtitle) if subtitle else ""
    if sub and sub != name and len(name) <= max_title_len:
        if sub.startswith("["):
            combined = f"{name} ({sub})"
        else:
            combined = f"{name} [{sub}]"
        if len(combined) > max_total_len:
            combined = combined[:max_total_len].rstrip(" []()")
        name = combined
    if len(name) > max_total_len:
        name = name[:max_total_len].rstrip(" []()")
    return name.strip()


def build_dir_name(title, subtitle, category="", lang="", max_title_len=40, max_total_len=100):
    """
    构建画廊目录名：[分类][语言] + 主标题[+副标题]
      - 分类/语言为空时省略对应前缀
      - 总长超 max_total_len 时截断（保证 Windows 路径安全）
    """
    prefix = ""
    if category:
        prefix += f"[{category}]"
    if lang:
        prefix += f"[{lang}]"
    base = build_base_name(title, subtitle, max_title_len, max_total_len)
    if not base:
        return prefix or ""
    name = prefix + base
    if len(name) > max_total_len:
        name = name[:max_total_len].rstrip(" []()")
    return name.strip()


# 语言标签集合（用于从 language 分组中识别实际语言值）
LANGUAGE_TAGS = {
    "chinese", "english", "japanese", "korean", "french", "spanish",
    "german", "russian", "thai", "vietnamese", "italian", "portuguese",
    "indonesian", "polish", "turkish", "arabic",
}


def extract_language_tag(info):
    """
    从标签 language 分组中提取实际语言值（如 chinese）
    无 language 分组或分组内只有 translated/speechless 等非语言标签时返回 None
    """
    for group, tags in info.get("tags", []):
        if group == "language":
            for t in tags:
                if t in LANGUAGE_TAGS:
                    return t
            return None
    return None


def format_translated(word, trans_dict):
    """双语格式：有译文 → "english (中文)"；无译文 → 纯英文"""
    zh = trans_dict.get(word)
    return f"{word} ({zh})" if zh else word


def escape_md_cell(text):
    """转义 markdown 表格单元格中的 | 字符"""
    return text.replace("|", "\\|")


def build_info_md(info, gallery_url):
    """
    生成 info.md 内容：基本信息表 + 标签表（单元格内每行一个标签，防爆格）
    标签按 "英文 (中文)" 双语显示，词典没有的保持纯英文
    """
    lines = [f"# {info['title']}", ""]

    # 基本信息表
    rows = []
    for label, value in (
        ("副标题", info["subtitle"]),
        ("分类", info["category"]),
        ("上传者", info["uploader"]),
        ("发布时间", info["posted"]),
        ("语言", info["language"]),
        ("文件大小", info["file_size"]),
        ("页数", info["length"]),
        ("收藏", info["favorited"]),
        ("评分", info["rating"]),
    ):
        if value:
            rows.append((label, escape_md_cell(value)))
    lines.append("| 项目 | 内容 |")
    lines.append("| --- | --- |")
    for label, value in rows:
        lines.append(f"| {label} | {value} |")

    # 标签表（每行一个标签，<br> 换行）
    if info["tags"]:
        lines.append("")
        lines.append("## 标签")
        lines.append("")
        lines.append("| 分组 | 标签 |")
        lines.append("| --- | --- |")
        for group, tags in info["tags"]:
            group_label = escape_md_cell(format_translated(group, GROUP_PREFIX_TRANSLATIONS))
            tag_cells = [
                escape_md_cell(format_translated(t, TAG_TRANSLATIONS)) for t in tags
            ]
            lines.append(f"| {group_label} | {'<br>'.join(tag_cells)} |")

    lines.append("")
    lines.append(f"画廊链接: {gallery_url}")
    lines.append("")
    return "\n".join(lines)


def build_save_filename(page, shown_name, img_url):
    """构建保存文件名：{页码:04d}_{网页显示名}，缺扩展名时从图片 URL 推断"""
    name = sanitize_filename(shown_name)
    if not name:
        name = f"page_{page}"
    # 无扩展名时从图片 URL 路径推断
    if not Path(name).suffix:
        m = re.search(r"\.(\w{2,5})$", img_url.split("?")[0])
        if m:
            name += "." + m.group(1)
        else:
            name += ".jpg"
    return f"{page:04d}_{name}"


def create_direct_session(config):
    """
    创建直连 Session（trust_env=False，绕过系统代理）
    用于图片下载通道：某些系统代理会中止 hath.network 图片节点的连接，
    直连反而稳定；直连不通时再回退到代理通道
    """
    session = requests.Session()
    session.trust_env = False
    session.headers.update(config["headers"])
    return session


def download_image_with_retry(session, direct_session, config, img_url, referer, save_path):
    """
    双通道带重试的图片下载：
      通道1（直连）: 绕过系统代理，单次尝试、短超时（快速失败）
      通道2（代理）: 走主 session（系统代理/配置代理），完整重试与指数退避
    校验状态码、内容非空、Content-Length 一致，返回是否成功
    """
    retry_cfg = config["retry"]
    headers = {"Referer": referer}

    def try_download(sess, timeout, max_attempts, label):
        """单通道下载：成功返回 (True, data)，失败返回 (False, None)"""
        for attempt in range(1, max_attempts + 1):
            try:
                resp = sess.get(img_url, headers=headers, timeout=timeout)
                if resp.status_code != 200:
                    print(f"    [{label} {attempt}/{max_attempts}] HTTP {resp.status_code}")
                else:
                    data = resp.content
                    if not data:
                        print(f"    [{label} {attempt}/{max_attempts}] 内容为空")
                    else:
                        content_length = resp.headers.get("Content-Length")
                        if content_length and len(data) != int(content_length):
                            # 内容被截断，重新下载
                            print(f"    [{label} {attempt}/{max_attempts}] 大小不符，可能截断")
                        else:
                            return True, data
            except requests.RequestException as e:
                print(f"    [{label} {attempt}/{max_attempts}] {e}")
            if attempt < max_attempts:
                wait = retry_cfg["backoff_base"] * (retry_cfg["backoff_multiplier"] ** (attempt - 1))
                print(f"    等待 {wait}s 后重试...")
                time.sleep(wait)
        return False, None

    # 通道1: 直连单次尝试，超时上限 15s（快速失败，不拖慢整体进度）
    ok, data = try_download(direct_session, min(config["timeout_image"], 15), 1, "直连")
    if not ok:
        # 通道2: 主 session（代理），完整重试
        ok, data = try_download(session, config["timeout_image"], retry_cfg["max_attempts"], "代理")
    if not ok:
        return False
    with open(save_path, "wb") as f:
        f.write(data)
    return True


def parse_range_text(range_text, total):
    """
    解析下载范围文本 "1-10,20,30-40" → 有序去重的页码列表
    超出 1..total 的页码被忽略（返回时打印提示）
    """
    pages = set()
    for part in range_text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) == 2 and bounds[0].strip().isdigit() and bounds[1].strip().isdigit():
                start, end = int(bounds[0]), int(bounds[1])
                if start > end:
                    start, end = end, start
                pages.update(range(start, end + 1))
        elif part.isdigit():
            pages.add(int(part))
    valid = sorted(p for p in pages if 1 <= p <= total)
    ignored = sorted(pages - set(valid))
    if ignored:
        print(f"[范围提示] 以下页码超出总页数({total})已忽略: {ignored}")
    return valid


def load_progress(progress_path):
    """加载进度文件，不存在则返回空进度"""
    if progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded": [], "failed": [], "status": "in_progress"}


def save_progress(progress_path, data):
    """保存下载进度到 progress.json（每页下载后立即写入）"""
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_args():
    """
    解析命令行参数
    返回 (range_text, retry_failed, check_mode, 位置参数列表)
    """
    args = sys.argv[1:]
    retry_failed = False
    check_mode = False
    range_text = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--rd", "-rd"):
            retry_failed = True
        elif a in ("--check", "-check"):
            check_mode = True
        elif a in ("--range", "-range"):
            if i + 1 < len(args):
                range_text = args[i + 1]
                i += 1
        elif a.startswith("--range="):
            range_text = a.split("=", 1)[1]
        else:
            positional.append(a)
        i += 1
    return range_text, retry_failed, check_mode, positional


def main():
    """主函数：解析参数 → 获取画廊信息 → 逐页下载（含断点续传）"""

    range_text, retry_failed, check_mode, pos_args = parse_args()
    if not pos_args:
        print("用法: py download_gallery.py [--range 1-10,20] [--rd] [--check] <画廊URL>")
        print("  --range   只下载指定页码范围，如 --range 1-10,20,30-40")
        print("  --rd      重试 progress.json 中记录的所有失败页")
        print("  --check   检查 images/ 实际文件与记录是否一致，修复 failed 列表")
        sys.exit(1)

    config = load_config()
    session = create_session(config)
    # 图片下载直连通道（绕过系统代理，见 download_image_with_retry 说明）
    direct_session = create_direct_session(config)
    delay = config["request_delay"]

    # 解析画廊 URL
    gallery_url_arg = pos_args[0]
    base, gid, token = parse_gallery_url(gallery_url_arg)
    if not base:
        print(f"画廊 URL 格式不正确: {gallery_url_arg}")
        print("应为形如: https://e-hentai.org/g/3743290/8eee725d8c/")
        sys.exit(1)
    gallery_url = f"{base}/g/{gid}/{token}/"

    # 获取画廊信息（标题/副标题/标签等）
    print(f"正在解析画廊: {gallery_url}")
    gallery_info, gallery_err = fetch_gallery_info(session, config, base, gid, token)
    if gallery_info is None:
        if gallery_err == "not_available":
            print("该画廊不可用（网站返回 404），可能原因:")
            print("  1. 画廊已被网站删除;")
            print("  2. 画廊仅登录用户可见——若浏览器（已登录）能打开,")
            print("     请在 config.json 的 cookies 字段填入 ipb_member_id / ipb_pass_hash。")
        else:
            print("画廊页获取失败，请检查网络/代理配置。")
        sys.exit(1)
    title = gallery_info["title"]
    subtitle = gallery_info["subtitle"]
    # 从 Length 字段解析总页数（如 "1835 pages"）
    total = 0
    m = re.search(r"([\d,]+)\s*pages?", gallery_info["length"])
    if m:
        total = int(m.group(1).replace(",", ""))
    if not title:
        title = f"gallery_{gid}"
        print(f"未提取到标题，使用目录名: {title}")
    print(f"标题: {title}")
    if subtitle:
        print(f"副标题: {subtitle}")

    # 获取全部页面列表（config.use_mpv 开启时优先 MPV，否则直接缩略图解析）
    print("正在获取页面列表...")
    page_infos = None
    if config.get("use_mpv", False):
        page_infos = fetch_page_list_mpv(session, config, base, gid, token)
        if page_infos:
            print(f"MPV API 获取到 {len(page_infos)} 页")
        else:
            print("MPV API 不可用，回退到画廊页缩略图解析...")
    if page_infos is None:
        try:
            resp = session.get(gallery_url, timeout=config["timeout_page"])
            gallery_html = resp.text if resp.status_code == 200 else ""
        except requests.RequestException:
            gallery_html = ""
        page_infos = fetch_page_list_gdt(session, config, base, gid, token, gallery_html) if gallery_html else None
        if page_infos:
            print(f"缩略图解析获取到 {len(page_infos)} 页")
        else:
            print("页面列表获取失败，请检查网络或稍后重试。")
            sys.exit(1)

    page_infos.sort(key=lambda x: x["page"])
    # 按页码建索引，方便查找
    info_by_page = {}
    for info in page_infos:
        info_by_page.setdefault(int(info["page"]), info)
    total = total or len(page_infos)
    if total < len(page_infos):
        total = len(page_infos)
    print(f"总页数: {total}")

    # 创建画廊目录与进度文件
    # 目录名 = [分类][语言]主标题[+副标题]；旧规则目录已存在时沿用旧名（保证续传进度不丢）
    lang = extract_language_tag(gallery_info)
    old_dir_name = build_base_name(title, subtitle)
    new_dir_name = build_dir_name(title, subtitle, category=gallery_info["category"], lang=lang)
    if old_dir_name and (BASE_DIR / old_dir_name).exists():
        dir_name = old_dir_name
        print(f"检测到已有目录（旧命名），沿用: {dir_name}")
    else:
        dir_name = new_dir_name
    if not dir_name:
        dir_name = f"gallery_{gid}"
    gallery_dir = BASE_DIR / dir_name
    images_dir = gallery_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    progress_path = gallery_dir / "progress.json"

    # 每次运行都刷新 info.md（基本信息 + 双语标签表）
    info_md_path = gallery_dir / "info.md"
    try:
        info_md_path.write_text(build_info_md(gallery_info, gallery_url), encoding="utf-8")
        print(f"画廊信息已写入: {info_md_path.name}")
    except OSError as e:
        print(f"[警告] info.md 写入失败: {e}")

    progress = load_progress(progress_path)
    progress.update({
        "gallery_url": gallery_url,
        "gid": gid,
        "token": token,
        "title": title,
        "subtitle": subtitle,
        "total": total,
    })
    progress.setdefault("downloaded", [])
    progress.setdefault("failed", [])
    save_progress(progress_path, progress)

    # --- --check 验证模式：按 images/ 实际文件重建进度 ---
    if check_mode:
        existing_pages = set()
        if images_dir.exists():
            for f in images_dir.iterdir():
                if f.is_file():
                    m = re.match(r"^(\d+)_", f.name)
                    if m:
                        existing_pages.add(int(m.group(1)))
        all_pages = set(range(1, total + 1))
        truly_missing = sorted(all_pages - existing_pages)
        truly_downloaded = sorted(all_pages & existing_pages)
        progress["downloaded"] = truly_downloaded
        progress["failed"] = truly_missing
        progress["status"] = "complete" if not truly_missing else "in_progress"
        save_progress(progress_path, progress)

        print(f"\n验证完成！实际文件: {len(truly_downloaded)}/{total}, 缺失: {len(truly_missing)}")
        if truly_missing:
            print(f"缺失页码已加入 failed: {truly_missing}")
            print(f"建议运行: py download_gallery.py --rd {gallery_url_arg}")
        return

    # 计算本次下载的目标页码
    if range_text:
        selected_pages = parse_range_text(range_text, total)
        if not selected_pages:
            print("下载范围为空或全部超出总页数，退出。")
            sys.exit(1)
    else:
        selected_pages = list(range(1, total + 1))

    if retry_failed:
        # --rd 模式：只重试 failed 中落在范围内的页
        retry_pages = sorted(set(progress.get("failed", [])) & set(selected_pages))
        if not retry_pages:
            print("没有失败页需要重试。")
            return
        print(f"发现 {len(retry_pages)} 个失败页，开始重试...")
        # 从 failed 中移除待重试页（成功后加入 downloaded，失败则重新加回）
        progress["failed"] = [p for p in progress.get("failed", []) if p not in retry_pages]
        progress["status"] = "in_progress"
        save_progress(progress_path, progress)
        target_pages = retry_pages
    else:
        # 正常模式：范围内未下载的页（断点续传/补下载）
        downloaded_set = set(progress.get("downloaded", []))
        target_pages = [p for p in selected_pages if p not in downloaded_set]
        if not target_pages:
            if progress.get("status") == "complete":
                print("所有页已下载完成。")
            else:
                print(f"所选范围内 {len(selected_pages)} 页均已下载。")
            print("如需重试失败页，请添加 --rd 参数运行。")
            print("如需检查实际文件状态，请添加 --check 参数运行。")
            return

    print(f"本次将下载 {len(target_pages)} 页...")

    # 单线程逐页下载
    next_nl = None  # 逐页解析出的下一个 nl 预载令牌
    downloaded_set = set(progress.get("downloaded", []))
    failed_set = set(progress.get("failed", []))

    for page in target_pages:
        info = info_by_page.get(page)
        if not info:
            print(f"  ✗ 第 {page} 页: 未在页面列表中找到，跳过")
            failed_set.add(page)
            continue

        page_url = f"{base}/s/{info['key']}/{gid}-{page}"

        # 若文件已存在（如进度丢失后重跑），直接视为已下载
        existing = [f for f in images_dir.glob(f"{page:04d}_*") if f.is_file()]
        if existing:
            downloaded_set.add(page)
            failed_set.discard(page)
            progress["downloaded"] = sorted(downloaded_set)
            progress["failed"] = sorted(failed_set)
            save_progress(progress_path, progress)
            print(f"[{page}/{total}] 已存在: {existing[0].name}")
            continue

        # 随机等待，降低触发限流风险
        sleep_time = random.randint(int(delay["min"]), int(delay["max"]))
        print(f"[{page}/{total}] 等待 {sleep_time}s ...")
        time.sleep(sleep_time)

        # 访问查看页（带 nl 预载令牌）
        nl = info.get("nl") or next_nl
        fetch_url = page_url + (f"?nl={nl}" if nl else "")
        print(f"[{page}/{total}] 获取页面: /s/{info['key']}/{gid}-{page}")
        page_html = get_page_html_with_retry(session, config, fetch_url)
        if not page_html:
            failed_set.add(page)
            progress["failed"] = sorted(failed_set)
            save_progress(progress_path, progress)
            print(f"  ✗ 第 {page} 页: 页面获取失败，已记录")
            continue

        img_url, shown_name, new_nl = parse_view_page(page_html, page_url)
        if new_nl:
            next_nl = new_nl
        if not img_url:
            failed_set.add(page)
            progress["failed"] = sorted(failed_set)
            save_progress(progress_path, progress)
            print(f"  ✗ 第 {page} 页: 未解析出图片地址，已记录")
            continue

        filename = build_save_filename(page, shown_name, img_url)
        save_path = images_dir / filename
        if download_image_with_retry(session, direct_session, config, img_url, page_url, save_path):
            downloaded_set.add(page)
            failed_set.discard(page)
            progress["downloaded"] = sorted(downloaded_set)
            progress["failed"] = sorted(failed_set)
            save_progress(progress_path, progress)
            print(f"  ✓ {filename}")
        else:
            failed_set.add(page)
            progress["failed"] = sorted(failed_set)
            save_progress(progress_path, progress)
            print(f"  ✗ 第 {page} 页: 图片下载失败，已记录")

    # 更新整体状态
    all_pages = set(range(1, total + 1))
    if not failed_set and all_pages.issubset(downloaded_set):
        progress["status"] = "complete"
    else:
        progress["status"] = "in_progress"
    progress["downloaded"] = sorted(downloaded_set)
    progress["failed"] = sorted(failed_set)
    save_progress(progress_path, progress)

    # 输出统计信息
    print(f"\n下载完成！成功 {len(downloaded_set)}/{total}, 失败 {len(failed_set)}")
    if failed_set:
        print(f"失败页码: {sorted(failed_set)}")
        print(f"可运行: py download_gallery.py --rd {gallery_url_arg} 重试失败页")
    print(f"图片保存在: {images_dir}")


if __name__ == "__main__":
    # 强制 UTF-8 输出，避免 Windows 控制台中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    main()
