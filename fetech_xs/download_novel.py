import sys
import json
import re
import time
import random
from pathlib import Path

import requests

from sites import get_adapter


# 脚本所在目录
BASE_DIR = Path(__file__).parent
# 全局配置文件路径
CONFIG_PATH = BASE_DIR / "config.json"
# HTTP 请求超时时间（秒）
DEFAULT_TIMEOUT = 30
# 书籍输出根目录的默认值（相对路径按脚本目录解析，保证从任意 cwd 启动都落在同一处）
DEFAULT_OUTPUT_DIR = "Download"


def resolve_output_dir(value):
    """把 output_dir 配置/参数解析成绝对路径。

    - 空值 → 默认 Download/
    - 相对路径 → 相对脚本所在目录（不是 cwd），保证从任意目录启动结果一致
    - 绝对路径 → 原样使用
    """
    text = (value or "").strip()
    if not text:
        text = DEFAULT_OUTPUT_DIR
    p = Path(text).expanduser()
    p = p if p.is_absolute() else (BASE_DIR / p)
    try:
        return p.resolve()
    except OSError:  # 路径不存在等情况下 resolve 可能失败，退回未规范化的绝对路径
        return p


def load_config():
    """加载 config.json 中的全局配置，缺失的字段用内置默认值补全"""
    defaults = {
        "output_dir": DEFAULT_OUTPUT_DIR,
        # 代理：留空则不显式设置（requests 会自行读取系统代理：Windows 注册表 / macOS 网络设置）
        "proxy": "",
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
        # 用户配置覆盖默认值（未知字段一并保留，避免管理器写入的额外键被丢弃）
        for key in defaults:
            if key in user_config:
                if isinstance(defaults[key], dict):
                    defaults[key].update(user_config[key])
                else:
                    defaults[key] = user_config[key]
        for key, value in user_config.items():
            defaults.setdefault(key, value)
    return defaults


def create_session(config):
    """创建 requests.Session 并设置请求头，维持 Cookie 连续性"""
    session = requests.Session()
    session.headers.update(config["headers"])
    session.headers["Referer"] = config.get("base_url", "")

    # 配置代理（http/https，以及装了 pysocks 后的 socks5）
    # 留空则不设置 session.proxies，此时 requests 会走它自己的默认逻辑（读系统代理）
    proxy = (config.get("proxy") or "").strip()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


# 书名目录里 Windows 非法字符 → 全角等价字符（保留可读性，且与站点的全角写法统一）
_BOOK_NAME_MAP = {"\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
                  '"': "”", "<": "＜", ">": "＞", "|": "｜"}


def sanitize_book_name(name):
    """书名 → 可安全作为目录名的字符串（替换 Windows 非法字符，避免 mkdir 失败）。"""
    name = (name or "").strip()
    for ch, fw in _BOOK_NAME_MAP.items():
        name = name.replace(ch, fw)
    return name.strip(" .") or "未命名书籍"


def sanitize_filename(title):
    """将章节标题处理为安全的文件名。

    去掉"第X章"前缀；若去掉后为空（如标题就是"第1章"），则保留原标题，
    避免退化成 hash 文件名（v2.0 改进）。
    """
    name = re.sub(r"^第[^章]*章\s*", "", title)
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = name.strip()
    if not name:
        name = re.sub(r'[\\/:*?"<>|]', "", title).strip()
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


def expected_chapter_filename(chapter):
    """章节的期望文件名（必须与 save_chapter 完全一致）。"""
    return f"{chapter['index']:04d}_{sanitize_filename(chapter['title'])}.html"


def scan_chapters_dir(chapters_dir, chapters):
    """扫描磁盘，返回 (已就绪索引集合, 缺失章节列表, 过期文件名列表)。

    以「期望文件名」（索引 + 清洗后的标题）为准比对，因此能识别
    「章节表更新导致旧文件失效」的情况（旧文件名不再匹配 → 算缺失）。
    - ready  ：索引 → 磁盘上存在对应期望文件的章节
    - missing：期望文件不存在的章节（需下载）
    - stale  ：磁盘上不属于任何期望文件的 .html（章节表变化后遗留的旧文件）
    """
    expected = {ch["index"]: expected_chapter_filename(ch) for ch in chapters}
    existing = set()
    if chapters_dir.exists():
        existing = {f.name for f in chapters_dir.iterdir() if f.is_file() and f.suffix == ".html"}
    ready = {i for i, name in expected.items() if name in existing}
    missing = [ch for ch in chapters if ch["index"] not in ready]
    wanted = set(expected.values())
    stale = sorted(n for n in existing if n not in wanted)
    return ready, missing, stale


def remove_stale_files(chapters_dir, stale):
    """删除过期章节文件（章节表更新后遗留），失败静默忽略。"""
    for name in stale:
        try:
            (chapters_dir / name).unlink()
        except OSError:
            pass


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


def download_with_retry(session, adapter, chapter, config):
    """带退避重试的章节下载。

    调用 adapter.download_chapter；失败时按指数退避等待后重试（最多 max_attempts 次）。
    返回 (是否成功, 正文HTML, 标题, 是否真实发了网络请求)。
    """
    cfg_retry = config["retry"]
    max_attempts = cfg_retry["max_attempts"]
    backoff_base = cfg_retry["backoff_base"]
    backoff_mult = cfg_retry["backoff_multiplier"]

    for attempt in range(1, max_attempts + 1):
        ok, html, title, fetched = adapter.download_chapter(session, chapter, config)
        if ok:
            return True, html, title, fetched
        if attempt < max_attempts:
            wait = backoff_base * (backoff_mult ** (attempt - 1))
            print(f"  [{attempt}/{max_attempts}] 下载失败, 等待 {wait}s 后重试...")
            time.sleep(wait)
    return False, None, None, False


def parse_args():
    """解析命令行参数，返回 (retry_failed, check_mode, output_dir, 位置参数)

    output_dir 为 --output-dir / --output_dir 的原始字符串；未指定时为 None，
    由调用方回落到 config.json 的 output_dir（再回落 DEFAULT_OUTPUT_DIR）。
    """
    args = sys.argv[1:]
    retry_failed = False
    check_mode = False
    output_dir = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--rd", "-rd"):
            retry_failed = True
        elif a in ("--check", "-check"):
            check_mode = True
        elif a in ("--output-dir", "-output-dir", "--output_dir", "-output_dir"):
            if i + 1 < len(args):
                output_dir = args[i + 1]
                i += 1
        elif a.startswith(("--output-dir=", "--output_dir=")):
            output_dir = a.split("=", 1)[1]
        else:
            positional.append(a)
        i += 1
    return retry_failed, check_mode, output_dir, positional


def main():
    """主函数：解析参数 → 分发站点适配器 → 获取书籍信息 → 逐章下载（含断点续传）"""

    retry_failed, check_mode, output_dir_arg, pos_args = parse_args()
    if not pos_args:
        print("用法: py -3 download_novel.py [--rd] [--check] [--output-dir DIR] <章节列表URL | book_id>")
        print("  支持站点: 爱丽丝书屋(als1004.space)、cool18(论坛型)")
        print("  --rd          重试 progress.json 中记录的所有失败章节（含 --check 发现的新章节）")
        print("  --check       重新抓取入口URL的最新章节表，与实际文件对比，修复 downloaded/failed")
        print(f"  --output-dir  书籍输出根目录（默认读 config.json 的 output_dir，当前默认 {DEFAULT_OUTPUT_DIR}）")
        sys.exit(1)

    # 加载配置
    config = load_config()
    output_root = resolve_output_dir(output_dir_arg or config.get("output_dir"))
    output_root.mkdir(parents=True, exist_ok=True)
    print(f"输出根目录: {output_root}")

    # 站点分发：按 URL 域名选择适配器；纯数字视为 als1004 book_id
    arg = pos_args[0]
    adapter = get_adapter(arg, config)
    print(f"站点: {adapter.type_id}")

    # 站点配置覆盖（cool18 可用 sites.cool18 覆盖代理/延迟等）
    site_config = adapter.site_config()
    session = create_session(site_config)
    delay = site_config["request_delay"]

    # 入口 URL 规整 + 抓取书籍信息（cool18 在此抓全部帖子并切章，含礼貌延迟）
    entry_url = adapter.resolve_entry(session, arg, site_config)
    print(f"正在解析章节列表: {entry_url}")
    book_info = adapter.fetch_book_info(session, entry_url, site_config)
    # 书名目录名做非法字符处理（如半角冒号在 Windows 上无法建目录）
    book_info["book_name"] = sanitize_book_name(book_info["book_name"])
    print(f"书名: {book_info['book_name']}")
    print(f"作者: {book_info['author']}")
    chapters = book_info["chapters"]
    total = len(chapters)
    print(f"章节数: {total}")

    # 创建书籍目录和进度文件路径
    book_dir = output_root / book_info["book_name"]
    book_dir.mkdir(parents=True, exist_ok=True)
    progress_path = book_dir / "progress.json"

    # 加载/初始化进度
    progress = load_progress(progress_path)
    progress["book_name"] = book_info["book_name"]
    progress["author"] = book_info["author"]
    progress["chapters_url"] = entry_url
    progress["total"] = total

    # 预填所有章节标题（本次抓取的最新完整标题，cool18 含小标题）
    progress["chapter_titles"] = {str(ch["index"]): ch["title"] for ch in chapters}
    save_progress(progress_path, progress)

    # --- --check 验证模式 ---
    if check_mode:
        chapters_dir = book_dir / "chapters"
        ready, missing, stale = scan_chapters_dir(chapters_dir, chapters)
        remove_stale_files(chapters_dir, stale)      # 章节表更新后遗留的旧文件

        missing_indices = [ch["index"] for ch in missing]
        progress["downloaded"] = sorted(ready)
        progress["failed"] = missing_indices
        progress["last_index"] = max(ready) if ready else -1
        progress["status"] = "complete" if not missing else "in_progress"
        save_progress(progress_path, progress)

        print(f"\n验证完成！实际文件: {len(ready)}/{total}, 缺失: {len(missing)}")
        if stale:
            print(f"已清理 {len(stale)} 个过期文件（章节表已更新）")
        if missing:
            print(f"缺失章节已加入 failed: {missing_indices}")
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
        # 按「期望文件名」核对磁盘：既能续传，也能识别章节表更新后旧文件失效
        chapters_dir = book_dir / "chapters"
        ready, missing, stale = scan_chapters_dir(chapters_dir, chapters)
        remove_stale_files(chapters_dir, stale)
        progress["downloaded"] = sorted(ready)
        progress["failed"] = []

        if not missing:
            progress["status"] = "complete"
            progress["last_index"] = max(ready) if ready else -1
            save_progress(progress_path, progress)
            print("所有章节已下载完成。直接运行 build_epub.py 生成 EPUB。")
            print("如需检查网站是否有更新章节，请运行 --check；有新章节后用 --rd 下载。")
            return

        if stale:
            print(f"检测到 {len(stale)} 个过期章节文件（章节表已更新），已清理。")
        if ready:
            print(f"已有 {len(ready)} 章已下载，继续未完成的部分。")
        progress["status"] = "in_progress"
        save_progress(progress_path, progress)
        download_targets = missing

    # 逐章下载
    for ch in download_targets:
        # 在正常模式下跳过已下载的章节
        if not retry_failed and ch["index"] in progress["downloaded"]:
            continue

        ok, content, real_title, fetched = download_with_retry(
            session, adapter, ch, site_config
        )
        if ok:
            saved_path = save_chapter(book_dir, ch, content)
            if ch["index"] not in progress["downloaded"]:
                progress["downloaded"].append(ch["index"])
            progress["last_index"] = ch["index"]
            # cool18 等站点的真实标题可能比章节表占位标题更完整（含小标题）
            if real_title and real_title != ch["title"]:
                progress["chapter_titles"][str(ch["index"])] = real_title
            save_progress(progress_path, progress)
            print(f"  ✓ {saved_path.name}")
        else:
            if ch["index"] not in progress.get("failed", []):
                progress["failed"] = sorted(set(progress.get("failed", [])) | {ch["index"]})
            save_progress(progress_path, progress)
            print(f"  ✗ 下载失败，已跳过")

        # 仅在真实发了网络请求时等待（cool18 缓存命中的章节不额外 sleep）
        if fetched:
            sleep_time = random.randint(delay["min"], delay["max"])
            print(f"[{ch['index']+1}/{total}] {ch['title']}  (等待 {sleep_time}s)")
            time.sleep(sleep_time)
        else:
            print(f"[{ch['index']+1}/{total}] {ch['title']}")

    # 标记完成（重试模式下也要更新状态）
    if not retry_failed or not progress.get("failed"):
        if not progress.get("failed"):
            progress["status"] = "complete"
            progress["total"] = total
    progress["downloaded"] = sorted(set(progress.get("downloaded", [])))
    progress["failed"] = sorted(set(progress.get("failed", [])))
    save_progress(progress_path, progress)

    # 输出统计信息
    print(f"\n下载完成！成功 {len(progress['downloaded'])}/{total}, 失败 {len(progress['failed'])}")
    if progress["failed"]:
        print(f"失败章节索引: {progress['failed']}")
    print(f"章节文件保存在: {book_dir / 'chapters'}")
    print(f"运行 build_epub.py 生成EPUB: py -3 build_epub.py \"{book_info['book_name']}\"")


if __name__ == "__main__":
    main()
