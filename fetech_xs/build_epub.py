import sys
import re
import json
from pathlib import Path

from ebooklib import epub
from bs4 import BeautifulSoup

# 脚本所在目录（配置文件所在位置）
BASE_DIR = Path(__file__).parent
# 全局配置文件路径（与 download_novel.py 共用同一份，保证输出目录一致）
CONFIG_PATH = BASE_DIR / "config.json"
# 书籍输出根目录的默认值（相对路径按脚本目录解析）
DEFAULT_OUTPUT_DIR = "Download"


def resolve_output_dir(value):
    """把 output_dir 配置/参数解析成绝对路径（与 download_novel.py 保持同一套规则）。

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


# 书名目录里 Windows 非法字符 → 全角等价字符（与 download_novel.py 保持一致）
_BOOK_NAME_MAP = {"\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
                  '"': "”", "<": "＜", ">": "＞", "|": "｜"}


def sanitize_book_name(name):
    """书名 → 可安全作为目录名的字符串（与 download_novel.py 一致，保证能找到目录）。"""
    name = (name or "").strip()
    for ch, fw in _BOOK_NAME_MAP.items():
        name = name.replace(ch, fw)
    return name.strip(" .") or "未命名书籍"


def load_config_output_dir():
    """读取 config.json 中的 output_dir；读不到就用默认值（不报错、不阻断 EPUB 生成）"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f).get("output_dir")
        except (OSError, ValueError):
            pass
    return None


def parse_args():
    """解析命令行参数，返回 (output_dir, 位置参数)"""
    args = sys.argv[1:]
    output_dir = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--output-dir", "-output-dir", "--output_dir", "-output_dir"):
            if i + 1 < len(args):
                output_dir = args[i + 1]
                i += 1
        elif a.startswith(("--output-dir=", "--output_dir=")):
            output_dir = a.split("=", 1)[1]
        else:
            positional.append(a)
        i += 1
    return output_dir, positional


def load_chapter_titles(book_dir):
    """
    从 progress.json 加载完整章节标题映射
    返回 {序号(字符串): "完整标题（含第X章）"} 的字典
    """
    progress_path = book_dir / "progress.json"
    if progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            pg = json.load(f)
        return pg.get("chapter_titles", {})
    return {}


def load_author(book_dir):
    """从 progress.json 读取作者信息"""
    progress_path = book_dir / "progress.json"
    if progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            pg = json.load(f)
        return pg.get("author", "未知作者")
    return "未知作者"


def scan_chapters(book_dir):
    """
    扫描 <书名>/chapters/ 目录下的所有 .html 章节文件
    按文件名数字前缀排序（0000, 0001, …）
    优先从 progress.json 读取完整标题（含第X章），否则从文件名推断
    返回 [(序号, 完整标题, HTML内容), …]
    """
    chapters_dir = book_dir / "chapters"
    if not chapters_dir.exists():
        print(f"错误: 未找到章节目录 {chapters_dir}")
        print("请先运行 download_novel.py 下载小说章节。")
        sys.exit(1)

    files = sorted(chapters_dir.glob("*.html"))
    if not files:
        print(f"错误: 章节目录为空 {chapters_dir}")
        sys.exit(1)

    # 加载完整章节标题映射
    chapter_titles = load_chapter_titles(book_dir)

    chapters = []
    for fpath in files:
        stem = fpath.stem  # 不含扩展名的文件名
        # 从文件名解析序号和标题：{序号}_{标题}.html
        m = re.match(r"(\d+)_(.+)", stem)
        if m:
            index = int(m.group(1))
            # 优先使用 progress.json 中的完整标题（含"第X章"）
            title = chapter_titles.get(str(index), m.group(2))
        else:
            index = len(chapters)
            title = stem
        with open(fpath, encoding="utf-8") as f:
            html_content = f.read()
        chapters.append((index, title, html_content))

    chapters.sort(key=lambda x: x[0])  # 按序号排序，确保章节顺序正确
    return chapters


def build_epub(book_name, author, chapters):
    """
    构建 EPUB 电子书：
    - 设置元数据（书名、作者、语言）
    - 为每章创建 EpubHtml（带标题和内容）
    - 自动生成目录（TOC），兼容 EPUB2（NCX）和 EPUB3（Nav）
    """
    book_id = f"ftech_xs_{book_name}"
    novel = epub.EpubBook()
    novel.set_identifier(book_id)
    novel.set_title(book_name)
    novel.set_language("zh-CN")
    if author:
        novel.add_author(author)

    # 默认样式：段首缩进两字、行距1.8、居中标题
    css_content = """
    p { text-indent: 2em; line-height: 1.8; margin: 0.5em 0; }
    h2 { text-align: center; font-size: 1.4em; margin: 1em 0; }
    body { font-family: SimSun, serif; }
    """
    css = epub.EpubItem(
        uid="style",
        file_name="style/default.css",
        media_type="text/css",
        content=css_content,
    )
    novel.add_item(css)

    # 逐个添加章节
    epub_chapters = []
    spine = ["nav"]
    for idx, title, html_content in chapters:
        ch = epub.EpubHtml(
            title=title,
            file_name=f"chapter_{idx:04d}.xhtml",
            lang="zh-CN",
        )
        # 在章节内容前插入标题
        wrapped = f"<h2>{title}</h2>\n{html_content}"
        ch.content = wrapped
        ch.add_item(css)
        novel.add_item(ch)
        epub_chapters.append(ch)
        spine.append(ch)

    # 设置目录（自动生成 NCX + Nav）
    novel.toc = epub_chapters
    novel.add_item(epub.EpubNcx())
    novel.add_item(epub.EpubNav())
    novel.spine = spine

    return novel


def main():
    """主函数：读取进度 → 扫描章节 → 构建 EPUB → 输出文件"""
    output_dir_arg, pos_args = parse_args()
    if not pos_args:
        print("用法: py -3 build_epub.py [--output-dir DIR] <小说书名>")
        print("示例: py -3 build_epub.py 召唤圣剑")
        print(f"  --output-dir  书籍输出根目录（默认读 config.json 的 output_dir，当前默认 {DEFAULT_OUTPUT_DIR}）")
        sys.exit(1)

    book_name = sanitize_book_name(pos_args[0])
    # 输出根目录：命令行参数 > config.json > 内置默认（相对路径按脚本目录解析）
    output_root = resolve_output_dir(output_dir_arg or load_config_output_dir())
    book_dir = output_root / book_name
    if not book_dir.exists():
        print(f"错误: 未找到小说目录 {book_dir}")
        sys.exit(1)

    author = load_author(book_dir)

    print(f"正在扫描章节文件: {book_dir / 'chapters'}")
    chapters = scan_chapters(book_dir)
    print(f"共发现 {len(chapters)} 章")

    print("正在构建EPUB...")
    novel = build_epub(book_name, author, chapters)

    output_path = book_dir / f"{book_name}.epub"
    epub.write_epub(str(output_path), novel, {})
    print(f"EPUB 生成成功: {output_path}")


if __name__ == "__main__":
    main()
