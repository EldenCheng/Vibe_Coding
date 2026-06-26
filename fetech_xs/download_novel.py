import sys
import json
import re
import time
import random
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# 脚本所在目录
BASE_DIR = Path(__file__).parent
# 全局配置文件路径
CONFIG_PATH = BASE_DIR / "config.json"
# HTTP 请求超时时间（秒）
DEFAULT_TIMEOUT = 30


def load_config():
    """加载 config.json 中的全局配置，缺失的字段用内置默认值补全"""
    defaults = {
        "request_delay": {"min": 15, "max": 30},
        "retry": {"max_attempts": 5, "backoff_base": 30, "backoff_multiplier": 2},
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        },
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
    """创建 requests.Session 并设置请求头，维持 Cookie 连续性"""
    session = requests.Session()
    session.headers.update(config["headers"])
    session.headers["Referer"] = config.get("base_url", "")
    return session


def fetch_book_info(session, chapters_url):
    """
    从章节列表页提取小说信息：
    - 书名（《》内文字）
    - 作者
    - book_id（URL 中的数字 ID）
    - source_id（章节链接中的源 ID）
    - 全部章节列表
    """
    resp = session.get(chapters_url, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # 提取书名：<div class="mu_h1"><h1>《书名》</h1>
    title_tag = soup.select_one("div.mu_h1 h1")
    if title_tag:
        raw_title = title_tag.get_text(strip=True)
        m = re.search(r"《(.+?)》", raw_title)
        book_name = m.group(1) if m else raw_title
    else:
        book_name = "未知书名"

    # 提取作者
    author_tag = soup.select_one("span:has(a[href*='/search/']) a")
    author = author_tag.get_text(strip=True) if author_tag else "未知作者"

    # 从章节列表 URL 中提取 book_id
    m = re.search(r"/id/(\d+)", chapters_url)
    book_id = int(m.group(1)) if m else 0

    # 从第一个章节链接中提取 source_id（/book/{source_id}/{hash}.html）
    source_id = 0
    first_link = soup.select_one("ul.mulu_list li a")
    if first_link:
        m = re.search(r"/book/(\d+)/", first_link.get("href", ""))
        if m:
            source_id = int(m.group(1))

    # 提取所有章节信息
    chapters = extract_chapters(soup, source_id)

    return {
        "book_name": book_name,
        "author": author,
        "book_id": book_id,
        "source_id": source_id,
        "chapters": chapters,
    }


def extract_chapters(soup, source_id):
    """
    解析 <ul class="mulu_list"> 中的章节链接
    过滤掉卷标（如"第一部 黄昏篇"），只保留含"章"字的正式章节
    返回按顺序排列的章节列表
    """
    chapters = []
    index = 0
    for li in soup.select("ul.mulu_list li"):
        a = li.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        # 跳过不含"章"的链接（卷标/分卷标题）
        if "章" not in title:
            continue
        # 提取章节 hash（URL 中的十六进制部分）
        m = re.search(r"/book/\d+/([a-f0-9]+)\.html", href)
        if not m:
            continue
        chapter_hash = m.group(1)
        chapters.append({
            "index": index,
            "title": title,
            "hash": chapter_hash,
            "url": f"/book/{source_id}/{chapter_hash}.html",
        })
        index += 1
    return chapters


def download_chapter_html(session, base_url, source_id, chapter_hash, referer):
    """
    方式A：通过 HTML 页面下载章节内容
    解析 <div class="read-content j_readContent"> 中的 innerHTML
    返回 (是否成功, 内容/错误信息)
    """
    url = f"{base_url}/book/{source_id}/{chapter_hash}.html"
    headers = {"Referer": referer}
    resp = session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    soup = BeautifulSoup(resp.text, "lxml")
    content_div = soup.select_one("div.read-content.j_readContent")
    if content_div is None:
        return False, "no content div"
    html = "".join(str(tag) for tag in content_div.children)
    if not html.strip():
        return False, "empty content"
    return True, html


def download_chapter_ajax(session, base_url, source_id, chapter_hash):
    """
    方式B：通过 AJAX API 接口下载章节内容（HTML方式失败的备选）
    GET /home/chapter/info?id={source_id}&key={hash}
    返回 JSON {code:1, data:{chapter:{content:"..."}}}
    """
    url = f"{base_url}/home/chapter/info"
    params = {"id": source_id, "key": chapter_hash}
    headers = {
        "Referer": base_url,
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = session.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        return False, f"AJAX HTTP {resp.status_code}"
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return False, "AJAX JSON decode error"
    if data.get("code") != 1:
        return False, f"AJAX code {data.get('code')}"
    content = data.get("data", {}).get("chapter", {}).get("content", "")
    if not content.strip():
        return False, "AJAX empty content"
    return True, content


def sanitize_filename(title):
    """将章节标题处理为安全的文件名：去掉"第X章"前缀，移除非法字符"""
    name = re.sub(r"^第[^章]*章\s*", "", title)
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = name.strip()
    if not name:
        name = str(hash(title))
    return name


def save_chapter(book_dir, chapter_info, html_content):
    """将章节 HTML 内容保存到 <书名>/chapters/{序号}_{标题}.html"""
    chapters_dir = book_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    safe_title = sanitize_filename(chapter_info["title"])
    filename = f"{chapter_info['index']:04d}_{safe_title}.html"
    filepath = chapters_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filepath


def load_progress(progress_path):
    """加载进度文件，不存在则返回空进度"""
    if progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded": [], "failed": [], "last_index": -1, "status": "in_progress"}


def save_progress(progress_path, data):
    """保存下载进度到 progress.json（每次下载一章后立即写入）"""
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download_with_retry(session, config, base_url, source_id, chapter, referer):
    """
    带重试的章节下载：
    1. 优先用 HTML 页面下载
    2. 若返回空则自动切换到 AJAX API
    3. 仍失败则按指数退避等待后重试（最多 max_attempts 次）
    """
    cfg_retry = config["retry"]
    max_attempts = cfg_retry["max_attempts"]
    backoff_base = cfg_retry["backoff_base"]
    backoff_mult = cfg_retry["backoff_multiplier"]

    for attempt in range(1, max_attempts + 1):
        # 先尝试 HTML 方式
        success, result = download_chapter_html(
            session, base_url, source_id, chapter["hash"], referer
        )
        if not success:
            # HTML 失败时切换 AJAX API
            success2, result2 = download_chapter_ajax(
                session, base_url, source_id, chapter["hash"]
            )
            if success2:
                return True, result2
            if attempt < max_attempts:
                wait = backoff_base * (backoff_mult ** (attempt - 1))
                print(
                    f"  [{attempt}/{max_attempts}] 空内容, 等待 {wait}s 后重试... ({result}/{result2})"
                )
                time.sleep(wait)
        else:
            return True, result

    return False, None


def parse_args():
    """解析命令行参数，返回 (retry_failed, check_mode, 位置参数)"""
    args = sys.argv[1:]
    retry_failed = False
    check_mode = False
    positional = []
    for a in args:
        if a in ("--rd", "-rd"):
            retry_failed = True
        elif a in ("--check", "-check"):
            check_mode = True
        else:
            positional.append(a)
    return retry_failed, check_mode, positional


def main():
    """主函数：解析参数 → 获取书籍信息 → 逐章下载（含断点续传）"""

    retry_failed, check_mode, pos_args = parse_args()
    if not pos_args:
        print("用法: py -3 download_novel.py [--rd] [--check] <章节列表URL | book_id>")
        print("  --rd      重试 progress.json 中记录的所有失败章节")
        print("  --check   检查实际下载文件与记录是否一致，修复 failed 列表")
        sys.exit(1)

    # 加载配置并创建 HTTP 会话
    config = load_config()
    session = create_session(config)
    delay = config["request_delay"]

    # 解析参数：纯数字视为 book_id，否则视为完整 URL
    arg = pos_args[0]
    if arg.isdigit():
        chapters_url = f"https://xn--1jqx9a.als1004.space/other/chapters/id/{arg}.html"
    else:
        chapters_url = arg

    # 从 URL 中提取基础域名
    base_domain_search = re.search(r"(https?://[^/]+)", chapters_url)
    base_url = base_domain_search.group(1) if base_domain_search else "https://xn--1jqx9a.als1004.space"

    # 获取书籍信息
    print(f"正在解析章节列表: {chapters_url}")
    book_info = fetch_book_info(session, chapters_url)
    print(f"书名: {book_info['book_name']}")
    print(f"作者: {book_info['author']}")
    print(f"章节数: {len(book_info['chapters'])}")

    # 创建书籍目录和进度文件路径
    book_dir = BASE_DIR / book_info["book_name"]
    book_dir.mkdir(parents=True, exist_ok=True)
    progress_path = book_dir / "progress.json"

    # 加载/初始化进度
    progress = load_progress(progress_path)
    progress["book_name"] = book_info["book_name"]
    progress["author"] = book_info["author"]
    progress["chapters_url"] = chapters_url

    chapters = book_info["chapters"]
    total = len(chapters)

    # 预填所有章节标题（来自网页抓取，确保完整准确）
    progress["chapter_titles"] = {str(ch["index"]): ch["title"] for ch in chapters}
    save_progress(progress_path, progress)

    # --- --check 验证模式 ---
    if check_mode:
        chapters_dir = book_dir / "chapters"
        existing_indices = set()
        if chapters_dir.exists():
            for f in chapters_dir.iterdir():
                if f.is_file() and f.suffix == ".html":
                    m = re.match(r"(\d+)_", f.stem)
                    if m:
                        existing_indices.add(int(m.group(1)))

        all_indices = set(range(total))
        truly_missing = sorted(all_indices - existing_indices)
        truly_downloaded = sorted(all_indices & existing_indices)

        progress["downloaded"] = truly_downloaded
        progress["failed"] = truly_missing
        progress["last_index"] = max(truly_downloaded) if truly_downloaded else -1
        progress["status"] = "complete" if not truly_missing else "in_progress"
        progress["total"] = total
        save_progress(progress_path, progress)

        print(f"\n验证完成！实际文件: {len(truly_downloaded)}/{total}, 缺失: {len(truly_missing)}")
        if truly_missing:
            print(f"缺失章节已加入 failed: {truly_missing}")
            print(f"建议运行: py -3 download_novel.py --rd {arg}")
        return

    # --- 处理 --rd 重试模式 ---
    if retry_failed:
        retry_indices = sorted(set(progress.get("failed", [])))
        if not retry_indices:
            print("没有失败章节需要重试。")
            return
        print(f"发现 {len(retry_indices)} 个失败章节，开始重试...")
        # 从 failed 中移除待重试章节（成功后会加入 downloaded 而非 failed）
        progress["failed"] = [i for i in progress.get("failed", []) if i not in retry_indices]
        progress["status"] = "in_progress"
        save_progress(progress_path, progress)  # 立即保存避免崩溃丢状态
        download_targets = [ch for ch in chapters if ch["index"] in retry_indices]

    else:
        # --- 正常下载 / 断点续传 ---
        if progress["status"] == "complete":
            print("所有章节已下载完成。直接运行 build_epub.py 生成 EPUB。")
            print("如需重试失败章节，请添加 --rd 参数运行。")
            print("如需检查实际文件状态，请添加 --check 参数运行。")
            return

        if progress["downloaded"]:
            print(f"已有 {len(progress['downloaded'])} 章已下载，继续未完成的部分。")

        # 断点续传：从上次最后位置之后开始
        start = 0
        if progress["last_index"] >= 0:
            start = progress["last_index"] + 1
        download_targets = chapters[start:]

    # 逐章下载
    for ch in download_targets:
        # 在正常模式下跳过已下载的章节
        if not retry_failed and ch["index"] in progress["downloaded"]:
            continue

        ok, content = download_with_retry(
            session, config, base_url, book_info["source_id"], ch, chapters_url
        )
        if ok:
            saved_path = save_chapter(book_dir, ch, content)
            if ch["index"] not in progress["downloaded"]:
                progress["downloaded"].append(ch["index"])
            progress["last_index"] = ch["index"]
            save_progress(progress_path, progress)
            print(f"  ✓ {saved_path.name}")
        else:
            if ch["index"] not in progress.get("failed", []):
                progress["failed"] = sorted(set(progress.get("failed", [])) | {ch["index"]})
            save_progress(progress_path, progress)
            print(f"  ✗ 下载失败，已跳过")
        
        sleep_time = random.randint(delay["min"], delay["max"])
        print(f"[{ch['index']+1}/{total}] {ch['title']}  (等待 {sleep_time}s)")
        time.sleep(sleep_time)

    # 标记完成（重试模式下也要更新状态）
    if not retry_failed or not progress.get("failed"):
        if not progress.get("failed"):
            progress["status"] = "complete"
            progress["total"] = total
    save_progress(progress_path, progress)

    # 输出统计信息
    print(f"\n下载完成！成功 {len(progress['downloaded'])}/{total}, 失败 {len(progress['failed'])}")
    if progress["failed"]:
        print(f"失败章节索引: {progress['failed']}")
    print(f"章节文件保存在: {book_dir / 'chapters'}")
    print(f"运行 build_epub.py 生成EPUB: py -3 build_epub.py \"{book_info['book_name']}\"")


if __name__ == "__main__":
    main()
