"""cool18（论坛型小说站）适配器。

站点特点：一个帖子（threadview）正文里含一批章节，后续章节可能有 4 种发布方式：
  A. 作者在正文开头维护的章节列表链接
  B. 以「跟贴」发布（静态页里跟贴列表为空，需调 AJAX 接口 achildlist）
  C. 单帖（以上都没有）
  D. 搜索页（threadsearch）结果聚合

统一模型：把入口解析成「一批帖子源」，每个帖子源抓正文并切章，按章节号去重合并。

章节切分（正文 <div class="content-section"><pre> 内）：
  - 第X章 + 小标题 / 【字数】 / 中文·阿拉伯·全角数字
  - 裸数字段落（早期帖子）
  - 尾部无编号「番外：…」段（35+番外）
  - ===== 分隔线清理、书名噪声清理

抓取策略：fetch_book_info 一次抓完全部帖子源并缓存切章结果（_split_cache），
download_chapter 直接取缓存（fetched=False，不重复请求）。
"""
import difflib
import html as html_mod
import random
import re
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from .base import SiteAdapter

DEFAULT_TIMEOUT = 30

# 中文数字映射（用于「第四十章」→ 40）
_CN_NUM = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
           '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100, '千': 1000}
_FW_DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')


def cn2int(s):
    """中文/阿拉伯/全角数字 → 阿拉伯数字。解析失败返回 None。"""
    if not s:
        return None
    s = s.strip().translate(_FW_DIGITS)
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in '一二三四五六七八九两':
            num = _CN_NUM[ch]
        elif ch in '十百千':
            unit = _CN_NUM[ch]
            if num == 0:
                num = 1
            total += num * unit
            num = 0
        else:
            return None
    return total + num


# 章节标记：段落边界（行首 / <br> / <p></p>）后跟 　*[（]第X章[小标题][）]，到 <br / <p></p> / < / 换行 为止
# 章节号支持中文/阿拉伯/全角数字/小数卷章号（如 2.1）；标记可被（括号）包裹（如（第47章 池中鸳鸯）（中））
_MARK_RE = re.compile(
    r"(?:^|(?:<br\s*/?>|<p></p>)|\n\s*)\s*　*(?:[（(]\s*)?第\s*([一二三四五六七八九十百千零〇两0-9０-９.]+)\s*章[ \u3000]*([^<\n]{0,40}?)?(?=(?:<br\s*/?>|<p></p>|<|\n|$))",
    re.M
)
# 特殊章名（无编号）：序章/序幕/幕间/终章/尾声；可带「第X卷」前缀
_SPECIAL_NAMES = ("序章", "序幕", "幕间", "终章", "尾声")
_SPECIAL_RE = re.compile(
    r"(?:^|(?:<br\s*/?>|<p></p>)|\n\s*)\s*　*(?:第\s*[一二三四五六七八九十百千零〇两0-9０-９]+\s*卷\s*)?"
    r"(序章|序幕|幕间|终章|尾声)[ \u3000]*([^<\n]{0,40}?)?(?=(?:<br\s*/?>|<p></p>|<|\n|$))",
    re.M
)
# 裸数字段落：数字后跟 <p></p> / <br> / 段尾（支持全角数字）
_BARE_RE = re.compile(
    r'(?:>|\u3000+|\s+)([0-9０-９]{1,3})\s*(?:<p></p>|<br\s*/?>\s*(?=<)|(?=<|$))', re.M
)
# 全角空格 + 4 位补零数字 + 紧跟标题（无「第X章」，如 `\u3000\u30000073她成为…`）
# 前导 0 是强信号（年份 2025 等不以 0 开头），可有效避开正文里的普通数字
_FMARK_RE = re.compile(r'\u3000+([0０][0-９]{3})(?=[^\d])([^<]*)')
# 全角空格 + 数字 + 「、」+ 标题（可被 <strong> 包裹），如 `\u3000\u3000<strong>1、十事神谕</strong>` / `\u3000\u300035、归心`
_CNUM_RE = re.compile(r'\u3000+\s*(?:<strong[^>]*>\s*)?([0-9０-９]{1,3})\s*、\s*([^<]*)(?:</strong>)?')
# 英文「Chapter/Chater + 数字」标记（作者常拼错/大小写不一，如 Chapter1 / chater16 / Chapter44、欲…）
_CHAPTER_EN_RE = re.compile(
    r"(?:^|(?:<br\s*/?>|<p></p>)|\n\s*)\s*(?:chapter|chater)\s*([0-9０-９]{1,3})\s*[、，,.:：]?[ \u3000]*([^<\n]{0,40}?)?(?=(?:<br\s*/?>|<p></p>|<|\n|$))",
    re.I | re.M
)
# 尾部无编号章节标题（「番外：×××」/「七夕特供礼物（上）（下）」）：短行标题 + 番外 或 （上/中/下）
_TRAIL_HEAD_RE = re.compile(
    r'(?:^|(?:<br\s*/?>|<p></p>)|\n\s*)\s*(?:番外|.{1,20}?[（(][上下中][)）])[^<\n]{0,20}?(?=(?:<br\s*/?>|<p></p>|(?=<)|$))',
    re.M
)
# 跟贴/列表项是否「章节帖」： 【书名】（范围）作者
_CHAPTER_SUBJECT_RE = re.compile(r'【[^】]+】\s*[（(].+?[)）]\s*作者')
# 作者列表链接的宽松判定（正文里的列表链接通常不带“作者：”后缀）
_LIST_CHAPTER_RE = re.compile(r'【[^】]+】\s*[（(].+?[)）]')
# 裸范围跟贴标题（无书名括号）：如 01-24、159-171（终）、40 完
_BARE_RANGE_RE = re.compile(r'^(\d{1,4}\s*[-~至]\s*\d{1,4}(?:\s*[（(][^）)]*[)）])?|\d{1,4}\s*(?:完|完结))$')
# 卷/节结构帖（老帖）跟贴标题：如 第一节　一步一个脚印（１－５）、第五节　１－２（卷分隔帖「第X卷」不抓）
_SECTION_SUBJECT_RE = re.compile(r'^\s*第[一二三四五六七八九十百0-9０-９]{1,3}节')
# 帖内小节标题行：第X节　标题（N）/（N上/下）/（上/下），全半角数字与空格随意；
# 不要求行首边界——有的标题和上一段正文粘在一起（作者忘换行）；
# 括号内是范围（如１－５）的不会误匹配（数字后跟非上下非右括号即失败）
_SECTION_HEAD_RE = re.compile(
    r'(第[一二三四五六七八九十百0-9０-９]{1,3}节)'
    r'[ \u3000]*([^<\n（(]{0,25}?)'
    r'\s*[（(]\s*([0-9０-９]{1,3})?\s*([上下])?\s*[)）]', re.M)


class Cool18Adapter(SiteAdapter):
    type_id = "cool18"
    domains = ["cool18.com"]
    site_key = "cool18"

    def __init__(self, config):
        super().__init__(config)
        self._split_cache = {}    # tid -> [(num, title, body)]
        self._tid_subject = {}    # tid -> subject（记录来源帖标题）
        self._requests = 0        # 本次运行已发请求数（用于礼貌延迟）

    # ---------------- 基础请求 ----------------

    def _get(self, session, url, config):
        """GET 带指数退避重试。失败返回 None。"""
        retry = config.get("retry") or {}
        max_a = retry.get("max_attempts", 1)
        base = retry.get("backoff_base", 30)
        mult = retry.get("backoff_multiplier", 2)
        timeout = config.get("timeout", DEFAULT_TIMEOUT)
        for attempt in range(1, max_a + 1):
            try:
                resp = session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp
            except requests.RequestException:
                pass
            if attempt < max_a:
                wait = base * (mult ** (attempt - 1))
                print(f"  [{attempt}/{max_a}] 请求失败, 等待 {wait}s 后重试... ({url[:90]})")
                time.sleep(wait)
        return None

    def _polite_sleep(self, config):
        """除第一个请求外，请求之间加随机礼貌延迟。"""
        if self._requests > 0:
            d = config.get("request_delay") or {}
            lo, hi = d.get("min", 10), d.get("max", 15)
            s = random.randint(lo, hi)
            print(f"  (站点礼貌延迟 {s}s)")
            time.sleep(s)
        self._requests += 1

    # ---------------- URL 工具 ----------------

    @staticmethod
    def _tid_of(url):
        m = re.search(r'tid=(\d+)', url)
        return m.group(1) if m else ""

    @staticmethod
    def _dir_base(url):
        """https://www.cool18.com/bbs4/index.php?… → https://www.cool18.com/bbs4/"""
        parsed = urlparse(url)
        dirpath = parsed.path.rsplit("/", 1)[0]
        return f"{parsed.scheme}://{parsed.netloc}{dirpath}/"

    def _resolve(self, entry_url, href):
        if not href:
            return None
        if href.startswith("http"):
            return href
        return self._dir_base(entry_url) + href.lstrip("/")

    @staticmethod
    def _search_keyword(url):
        q = parse_qs(urlparse(url).query)
        # threadsearch 用 keywords；search.php 全站搜索用 keyword（单数）
        return ((q.get("keywords") or q.get("keyword")) or [""])[0].strip()

    @staticmethod
    def _subject_of(a):
        """从搜索结果链接里提取帖子标题。

        search.php 的结果里每个 <a> 含两行 <p class="lf">：第一行是版块名
        （如【禁忌书屋】），第二行才是「【书名】（范围）作者」——取最后一行即可跳过版块名。
        threadsearch 的结果是纯文本，直接取整行。
        """
        lf = a.select("p.lf")
        if lf:
            return lf[-1].get_text("", strip=True)
        return a.get_text("", strip=True)

    @staticmethod
    def _search_author(url):
        """从搜索 URL 读取可选 &author= 限定参数（多书歧义时用于精确选书）。"""
        q = parse_qs(urlparse(url).query)
        return (q.get("author") or [""])[0].strip()

    # ---------------- 标题解析 ----------------

    @staticmethod
    def _parse_title(text):
        """从标题文本提取 (书名, 范围文本)。

        支持形态：【名】（1-3）作者：xx /《名》（全）作者：xx / 裸范围（如 01-24、159-171（终））
        无书名括号时返回 (None, 范围)；完全解析不出时返回 (None, None)。
        """
        m = re.search(r'[【《]([^】》]+)[】》]', text)
        book_name = m.group(1).strip() if m else None
        m2 = re.search(r'[（(]\s*([^）)]+?)\s*[)）]', text)
        rng = m2.group(1).strip() if m2 else ""
        if not m:
            # 没有书名括号：整条标题可能就是裸范围（跟贴常见）
            mb = _BARE_RANGE_RE.match(text.strip())
            if mb:
                rng = mb.group(1).strip()
        if not book_name and not rng:
            return None, None
        return book_name, (rng or None)

    @staticmethod
    def _author_from_title(text):
        m = re.search(r'作者\s*[:：]?\s*(\S+)', text)
        return m.group(1).strip() if m else "未知作者"

    @staticmethod
    def _author_from_content(content):
        """从正文头部「作者：xxx」提取作者（h1 未写作者时用）。"""
        m = re.search(r'作者\s*[:：]\s*([^\s<>（）()【】]+)', content[:400])
        return m.group(1).strip() if m else None

    @staticmethod
    def _looks_like_chapter(subject):
        return bool(_CHAPTER_SUBJECT_RE.search(subject or ""))

    def _single_num(self, subject):
        """标题范围是单章时返回（可能带卷号前缀的）章节号，用于无标记帖子的整篇兜底。"""
        _, rng = self._parse_title(subject)
        prefix, nums = self._range_info(rng)
        if len(nums) == 1 and isinstance(nums[0], int):
            return f"{prefix}{nums[0]}" if prefix else nums[0]
        return None

    def _num_prefix(self, subject):
        """标题范围带卷号时返回卷前缀（如 '2.'），否则 ''。"""
        _, rng = self._parse_title(subject)
        prefix, _ = self._range_info(rng)
        return prefix

    def _range_info(self, rng):
        """范围文本 → (卷号前缀, 章节号列表)。

        - '2.1-2.3' → ('2.', [1,2,3])      同卷内的分卷章节（卷号相同）
        - '2.1'     → ('2.', [1])
        - '1-5'     → ('',  [1,2,3,4,5])
        - '40'      → ('',  [40])
        - '1.0-2.3' → ('',  [])            跨卷合集（卷号不同，无法确定章节数）
        - '35+番外' → ('',  [35, '番外'])
        - 解析失败   → ('',  [])
        """
        if not rng:
            return "", []
        rng = rng.strip().translate(_FW_DIGITS)
        # 同卷分卷章节：2.1-2.3
        m = re.match(r'(\d+)\.(\d+)\s*[-~至]\s*(\d+)\.(\d+)$', rng)
        if m:
            if m.group(1) != m.group(3):
                return "", []          # 跨卷合集（如 1.0-2.3），不做分卷
            return f"{int(m.group(1))}.", list(range(int(m.group(2)), int(m.group(4)) + 1))
        # 单点带卷号：2.1
        m = re.match(r'(\d+)\.(\d+)$', rng)
        if m:
            return f"{int(m.group(1))}.", [int(m.group(2))]
        # 番外
        if "+" in rng:
            a, b = rng.split("+", 1)
            base = cn2int(a) or 0
            return "", [base, b.strip() or "番外"]
        # 普通区间 / 单章
        m = re.search(r'(\d+)\s*[-~至]\s*(\d+)', rng)
        if m:
            return "", list(range(int(m.group(1)), int(m.group(2)) + 1))
        # 「60完」「35+番外」：去掉 完/完结 后缀再判断单章号
        rng2 = re.sub(r'(完|完结)$', '', rng).strip()
        if rng2.isdigit():
            return "", [int(rng2)]
        n = cn2int(re.sub(r'[（(）)]', '', rng2))
        return ("", [n]) if n else ("", [])

    # ---------------- 切章 ----------------

    @staticmethod
    def _strip_post_header(body):
        """剥离帖子开头「【书名】（范围）作者：…日期…」头部段落，保留正文。

        兼容：书名/作者/日期 写在同一段（用 <br/> 分隔），或分成多个 <p></p> 段；
        正文前可能有零碎空白/换行/句点。
        """
        m = re.match(r'^\s*[^【<]*?(?=【)', body, re.S)   # 剥到第一个【书名】前
        if m:
            body = body[m.end():]
        rest = body
        for _ in range(8):   # 最多剥 8 个头部段落/行
            m = re.match(
                r'^\s*(?:'
                r'【[^<]{1,20}?】(?:[（(][^）)<]{0,40}[）)])[^<]{0,20}?\s*(?:作者[:：][^<]{0,120}?)?'
                r'|【[^<]{1,20}?】[^<]{0,20}?\s*作者[:：][^<]{0,120}?'
                r'|[^<]{0,40}?作者[:：][^<]{0,120}?'
                r'|[^<]{0,6}?(?:19|20)\d{2}[-/年.]\d{1,2}[^<]{0,10}?(?:发表于?|发布于?)[^<]{0,120}?'
                r'|字数[:：]\s*\d+[^<]{0,80}?'
                r'|是否首发[^<]{0,30}?'
                r')\s*(?:<p></p>|<br\s*/?>|\n)',
                rest, re.S)
            if not m:
                break
            rest = rest[m.end():]
        return rest.lstrip('\u3000 \t\r\n')

    def _split_content(self, content, book_names=(), fallback_num=None, expected_nums=None,
                       waizhuan=False, waizhuan_title="", section_subject=""):
        """正文 → [(章节号(int或str), 标题, 正文HTML)]。

        book_names：书名（可传字符串或字符串序列）——正文标记行常重复书名，
        切标题时去掉（新旧书名可能不同，故支持多个）。
        fallback_num：帖子标题范围是单章时传入；若正文里找不到任何章节标记，
        就把整篇当一章（论坛单章帖的常见写法）。
        expected_nums：帖子标题范围解析出的章节号列表（如 (45-46) → [45,46]），
        用于「范围帖开头无标记」时把第一个标记前的正文按范围首章号兜底。
        waizhuan / waizhuan_title：外传帖标记——外传短篇整帖作为一章（标题用外传名），
        不再按内部标记切章（外传内部章节号常与主线撞号）。
        """
        if isinstance(book_names, str):
            names = [book_names] if book_names else []
        else:
            names = [n for n in (book_names or ()) if n]
        content = re.sub(r'^\s*<pre>', '', content)
        # 去掉行内强调标签（<strong>/<b>），否则「被 <strong> 包住的章标记」识别不到
        content = re.sub(r'</?(?:strong|b)\b[^>]*>', '', content)
        # 卷/节结构帖（老帖）：帖内用「第X节　标题（N/上下/N上下）」标题行分小节，
        # 每个小节作为一章（章节号用帖内顺序，全局排序靠 tid+帖内顺序）；
        # 找不到标题行时整帖一章（标题用跟贴标题）
        if section_subject:
            heads = list(_SECTION_HEAD_RE.finditer(content))
            if heads:
                out = []
                for i, m in enumerate(heads):
                    end = heads[i + 1].start() if i + 1 < len(heads) else len(content)
                    sec, ttl, part, half = m.group(1), (m.group(2) or '').strip(), m.group(3), m.group(4)
                    label = (str(int(part.translate(_FW_DIGITS))) if part else '') + (half or '')
                    title = sec + (('　' + ttl) if ttl else '') + (f'（{label}）' if label else '')
                    body = content[m.end():end]
                    # 作者有时把同一小节重复粘贴（同名标题、内容相同）→ 保留更长版本；
                    # 同名但内容不同（如标题贴错的续段）→ 照常保留，不丢内容
                    if out and out[-1][1] == title:
                        prev = out[-1]
                        na = re.sub(r'\s|<[^>]+>', '', prev[2])
                        nb = re.sub(r'\s|<[^>]+>', '', body)
                        if self._similar_text(nb, na):
                            if len(nb) > len(na):
                                out[-1] = (prev[0], title, body)
                            continue
                    out.append((len(out) + 1, title, body))
                return out
            return [(1, section_subject.strip(), content)]
        # 外传帖：整帖作为一章，标题用帖子的外传名
        if waizhuan:
            wz_title = re.sub(r'\s*(完|完结)$', '', (waizhuan_title or "外传").strip())
            return [(wz_title, wz_title, self._strip_post_header(content))]
        # 正文头部通常也写一次书名（可能与入口 h1 的新书名不同，如改名后的旧名），
        # 一并纳入清理，避免书名残片进标题
        hm = re.search(r'【([^】]+)】', content[:300])
        if hm and hm.group(1).strip() not in names:
            names.append(hm.group(1).strip())

        def clean_title(n, sub):
            sub = (sub or '').strip()
            for nm in names:
                sub = sub.replace(nm, '')
            sub = re.sub(r'【字数[：:]\s*[\d,，]+】', '', sub).strip()
            sub = re.sub(r'^[\s：:，,、.。\-—]+', '', sub)   # 去掉小标题前的冒号/顿号等
            if re.fullmatch(r'[\d]+', sub or ''):   # 书名噪声留下的裸数字（如 "43"）
                sub = ''
            head = n if isinstance(n, str) and n in _SPECIAL_NAMES else f'第{n}章'
            return head + (f' {sub}' if sub else '')

        # 1) 第X章 标记（中文/阿拉伯/全角/小数卷章号 2.1）+ 特殊章名（序章/幕间/终章…）
        marks = []
        for m in _MARK_RE.finditer(content):
            raw = m.group(1).replace(' ', '').strip().translate(_FW_DIGITS)
            if '.' in raw:
                n = raw if re.fullmatch(r'\d+(\.\d+)+', raw) else None
            else:
                n = cn2int(raw)
            if n:
                sub = m.group(2) or ''
                # （第47章 池中鸳鸯）（中） 这类括号包裹标记：整理小标题里的残括号
                sub = re.sub(r'[）)]\s*（([^（）)]{1,8})）\s*$', r'（\1）', sub)
                # 只在括号不配对（外层包裹括号）时剥尾部 ）；嘴巴的开发（上）这类配对的不动
                if sub.count('（') != sub.count('）'):
                    sub = re.sub(r'[）)]+\s*$', '', sub)
                marks.append((m.start(), n, sub, m.end()))
        # 标题行标记：作者把「第X章」写在标题行末尾（如「凌辱之一生性奴（校园，凌辱，痴女，女主视觉） 第十七章」），
        # 行首的书名/标签导致 _MARK_RE 的行首边界对不上；书名还常被截断（如少个「凌」字）。
        # 规则：行首边界 + 第X章前 ≤45 字 + 章号在行尾；行内容含（、【或已知书名才认（避免正文误判）。
        _titleline = re.compile(
            r'(?:^|(?:<br\s*/?>|<p></p>)|\n)\s*([^<\n]{1,45}?)第\s*([一二三四五六七八九十百千零〇两0-9０-９.]+)\s*章[ \u3000]*([^<\n]{0,20}?)?(?=\n|<br\s*/?>|<p></p>|$)',
            re.M)
        for m in _titleline.finditer(content):
            line = m.group(1)
            if not (any(bn in line for bn in names) or '（' in line or '(' in line or '【' in line):
                continue
            raw = m.group(2).replace(' ', '').strip().translate(_FW_DIGITS)
            if '.' in raw:
                n = raw if re.fullmatch(r'\d+(\.\d+)+', raw) else None
            else:
                n = cn2int(raw)
            if n:
                sub = m.group(3) or ''
                sub = re.sub(r'[）)]\s*（([^（）)]{1,8})）\s*$', r'（\1）', sub)
                if sub.count('（') != sub.count('）'):
                    sub = re.sub(r'[）)]+\s*$', '', sub)
                marks.append((m.start(), n, sub, m.end()))
        for m in _SPECIAL_RE.finditer(content):
            marks.append((m.start(), m.group(1), m.group(2), m.end()))
        for m in _CHAPTER_EN_RE.finditer(content):
            n = cn2int(m.group(1))
            if n:
                marks.append((m.start(), n, m.group(2), m.end()))
        marks.sort(key=lambda x: x[0])
        # 合并相邻同号标记：作者常写「书名 第X章」标题行 + 独立「第X章」两连发 →
        # 紧邻（<40 字）时保留后一个（正文起点干净）；相隔远时后一个同号标记在前一章
        # 正文范围内（如 第一章标题行 + 契子 + 重复的 第一章）→ 是重复标记，丢弃后一个
        merged = []
        for m in marks:
            if merged and merged[-1][1] == m[1]:
                if m[0] - merged[-1][0] < 40:
                    merged[-1] = m
                continue
            merged.append(m)
        marks = merged
        if marks:
            result = []
            for i, (pos, n, sub, body_start) in enumerate(marks):
                end = marks[i + 1][0] if i + 1 < len(marks) else len(content)
                body = content[body_start:end]
                # 去掉标记行自身的终止符（<br> 或 <p></p>）及行首空白
                body = re.sub(r'^\s*(?:<br\s*/?>|<p></p>)+\s*', '', body)
                result.append((n, clean_title(n, sub), body))
            # 尾部无编号番外/特供章（「番外：×××」…「番外完」，或「七夕特供礼物（上）（下）」）
            last = result[-1]
            tail = list(_TRAIL_HEAD_RE.finditer(last[2]))
            if tail:
                body = last[2]
                pieces = []
                first_pos = tail[0].start()
                for i, m in enumerate(tail):
                    title = re.sub(r'<[^>]+>', '', m.group(0)).strip()
                    end = tail[i + 1].start() if i + 1 < len(tail) else len(body)
                    seg = re.sub(r'^\s*(?:<br\s*/?>|<p></p>)+\s*', '', body[m.end():end])
                    if i == 0:
                        pieces.append((last[0], last[1], body[:first_pos]))
                    num = f'{last[0]}番外' if i == 0 else f'{last[0]}番外{i + 1}'
                    pieces.append((num, title or f'第{last[0]}章 番外', seg))
                result[-1:] = pieces
            # 范围帖前缀拯救：帖子声明 (N-M) 但第一个标记的章节号 > N（开头章节没写标记，
            # 作者直接把正文贴上来）→ 把第一个标记前的正文按 N 兜底成缺失的开头章节
            if expected_nums and len(result) < len(expected_nums):
                first_num = result[0][0]
                if isinstance(first_num, int) and first_num > expected_nums[0]:
                    prefix = self._strip_post_header(content[:marks[0][0]])
                    if len(re.sub(r'\s|<[^>]+>', '', prefix)) >= 200:   # 有实质正文才兜底
                        result.insert(0, (expected_nums[0], f'第{expected_nums[0]}章', prefix))
            return result

        # 1.5) 全角空格 + 4 位补零数字 + 紧跟标题（无「第X章」，如 　　0073她成为…）
        fmarks = list(_FMARK_RE.finditer(content))
        if fmarks:
            result = []
            for i, m in enumerate(fmarks):
                n = int(m.group(1).translate(_FW_DIGITS))
                end = fmarks[i + 1].start() if i + 1 < len(fmarks) else len(content)
                body = content[m.end():end]
                body = re.sub(r'^\s*(?:<br\s*/?>|<p></p>)+\s*', '', body)
                result.append((n, clean_title(n, m.group(2)), body))
            return result

        # 1.6) 全角空格 + 数字 + 「、」 + 标题（可被 <strong> 包裹，如 　　1、十事神谕 / 　　35、归心）
        cmarks = list(_CNUM_RE.finditer(content))
        if cmarks:
            result = []
            for i, m in enumerate(cmarks):
                n = int(m.group(1).translate(_FW_DIGITS))
                end = cmarks[i + 1].start() if i + 1 < len(cmarks) else len(content)
                body = content[m.end():end]
                body = re.sub(r'^\s*(?:<br\s*/?>|<p></p>)+\s*', '', body)
                result.append((n, clean_title(n, m.group(2)), body))
            return result

        # 2) 裸数字段落
        nums = [(m.start(), int(m.group(1).translate(_FW_DIGITS))) for m in _BARE_RE.finditer(content)]
        seen, uniq = set(), []
        for p, n in nums:
            if n not in seen:
                seen.add(n)
                uniq.append((p, n))
        if uniq:
            keep = uniq
            # 优先按「标题范围」过滤；范围过大/不可解析时取连续递增段
            keep = self._filter_bare_numbers(uniq)
            if keep:
                result = []
                for i, (pos, n) in enumerate(keep):
                    end = keep[i + 1][0] if i + 1 < len(keep) else len(content)
                    body = content[pos:end]
                    bm = re.search(r'(?:<br\s*/?>|<p></p>)', body)
                    if bm:
                        body = body[bm.end():]
                    result.append((n, f'第{n}章', body))
                return result
        # 3) 兜底：标题范围是单章、但正文里找不到任何章节标记 → 整篇算一章
        if fallback_num:
            return [(fallback_num, f'第{fallback_num}章', self._strip_post_header(content))]
        return []

    def _filter_bare_numbers(self, uniq):
        """裸数字过滤：优先取标题区间内；区间不可用/过大时取连续递增段。"""
        # 尝试用来源帖标题的范围（self._tid_subject 里记录了当前帖 subject）
        # 此处无法拿 subject，改为：如果检测到的数字跨度 ≤25 且连续，直接信任；
        # 否则只保留连续递增段。
        nums = [n for _, n in uniq]
        if len(nums) >= 2 and max(nums) - min(nums) <= 25 and nums == sorted(nums):
            return uniq
        keep = [uniq[0]]
        for p, n in uniq[1:]:
            if n == keep[-1][1] + 1:
                keep.append((p, n))
            else:
                break
        return keep

    def _to_paragraphs(self, body):
        """正文 → <p> 段落 HTML（供 build_epub）。"""
        text = re.sub(r'^\s*<pre>', '', body)
        text = re.sub(r'\r\n', '\n', text)   # 统一换行，避免 Windows 写入时 \r\r\n 双转换
        # 老帖噪声：6park 水印（<font>包裹或裸文本）、版主编辑记录
        text = re.sub(r'<font[^>]*>\s*www\.6park\.com\s*</font>', '', text, flags=re.I)
        text = re.sub(r'www\.6park\.com', '', text, flags=re.I)
        text = re.sub(r'<b>版主[:：][^<]{0,60}编辑</b>', '', text)
        # 分隔符：<br> / <p></p> / 空行（LF 分隔的书用 \n\n 当段隔）
        parts = re.split(r'<br\s*/?>|<p></p>|\n[ \t\u3000]*\n', text)
        paras = []
        for p in parts:
            p = re.sub(r'<[^>]+>', '', p)          # 去掉残留标签（图片是纯文本文件名）
            p = html_mod.unescape(p)
            p = re.sub(r'^[\s\u3000]+', '', p)     # 去掉段首缩进（交给 CSS text-indent）
            p = p.strip()
            if p:
                paras.append(f'<p>{p}</p>')
        if not paras:
            return ""
        return "\n".join(paras)

    # ---------------- 帖子抓取与切章 ----------------

    def _content_div(self, soup):
        """取正文内容。

        优先取 <div class="content-section"><pre>（正文都在 pre 里），
        避开 </pre> 之后的广告位 / AI 标记 / 内联脚本等杂项——
        否则这些杂项会被当成最后一章的正文（会让去重/标题出错）。
        """
        pre = soup.select_one("div.content-section pre")
        if pre is not None:
            return pre.decode_contents()
        node = soup.select_one("div.content-section")
        if node is None:
            return None
        return node.decode_contents()

    def _fetch_and_split(self, session, url, config, book_name="", fallback_num=None, num_prefix="",
                         expected_nums=None, waizhuan=False, waizhuan_title="", section_subject=""):
        """抓取一个帖子页并切章，返回 [(num,title,body)]。失败返回 []。

        num_prefix：标题范围带卷号（如 '2.1-2.3'）时的卷前缀，切章后给章节号/标题
        补上卷号（正文里往往只写“第1章”）。
        expected_nums / waizhuan / waizhuan_title：透传给 _split_content
        （范围帖前缀兜底、外传帖整章处理）。
        section_subject：卷/节结构帖的跟贴标题（第X节开头），启用小节标题行切分。
        """
        self._polite_sleep(config)
        resp = self._get(session, url, config)
        if resp is None:
            print(f"  ✗ 抓取失败: {url}")
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        content = self._content_div(soup)
        if content is None:
            return []
        chs = self._split_content(content, book_name, fallback_num, expected_nums, waizhuan, waizhuan_title,
                                  section_subject)
        if num_prefix:
            chs = self._apply_num_prefix(chs, num_prefix)
        return chs

    @staticmethod
    def _apply_num_prefix(chs, prefix):
        """给章节号/标题补卷号前缀；正文已是“第2.1章”等带卷号时跳过。"""
        out = []
        for n, title, body in chs:
            key = str(n)
            if key.endswith("番外"):
                base = key[:-2]
                key = f"{prefix}{base}番外" if base.isdigit() else key
            elif not key.startswith(prefix):
                key = f"{prefix}{key}"
            m = re.match(r'^(第)(.+?)(章)(.*)$', title)
            if m and m.group(2) != key:
                title = f"第{key}章{m.group(4)}"
            out.append((key, title, body))
        return out

    def _fetch_replies(self, session, entry_url, config):
        """调 achildlist 接口取跟贴，返回 [(tid, subject)]，只留章节型跟贴。"""
        tid = self._tid_of(entry_url)
        if not tid:
            return []
        api = self._dir_base(entry_url) + f"index.php?app=forum&act=achildlist&tid={tid}"
        self._polite_sleep(config)
        resp = self._get(session, api, config)
        if resp is None:
            return []
        try:
            data = resp.json()
        except (ValueError, requests.RequestException):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            subj = str(item.get("subject") or "").strip()
            rtid = str(item.get("tid") or "")
            # 跟贴标题可能没有“作者”后缀（如【书名】（1-3）、（16-19）全文终）、
            # 是裸范围（如 01-24、159-171（终））或卷/节结构（第一节　标题（１－５））；
            # 评分/灌水等噪声不含这些格式会被过滤
            if rtid and subj and (_LIST_CHAPTER_RE.search(subj) or _BARE_RANGE_RE.match(subj)
                                  or _SECTION_SUBJECT_RE.match(subj)):
                out.append((rtid, subj))
        return out

    def _extract_list_links(self, content):
        """正文里作者维护的章节列表链接（第一个章节标记之前的 <a tid>）。

        注意：正文列表里的链接通常只有【书名】（范围），没有“作者：”后缀，
        所以这里用宽松判定（只要求书名+范围）。
        """
        first = _MARK_RE.search(content) or _BARE_RE.search(content)
        header = content[:first.start()] if first else content
        links = re.findall(r'href="[^"]*tid=(\d+)[^"]*"[^>]*>(.*?)</a>', header, re.S)
        out = []
        for tid, text in links:
            subj = re.sub(r'<[^>]+>', '', text).strip()
            if _LIST_CHAPTER_RE.search(subj):
                out.append((tid, subj))
        return out

    # ---------------- 章节表 ----------------

    def fetch_book_info(self, session, entry_url, config):
        low = entry_url.lower()
        self._requests = 0
        self._split_cache = {}    # 每次解析都从零开始，避免同一实例复用时互相污染
        self._tid_subject = {}
        if "threadsearch" in low or "action=search" in low or "search.php" in low:
            return self._from_search(session, entry_url, config)
        return self._from_thread(session, entry_url, config)

    def _from_thread(self, session, entry_url, config):
        """模式 A/B/C：主贴 + 作者列表链接 + 章节型跟贴。"""
        self._polite_sleep(config)
        resp = self._get(session, entry_url, config)
        if resp is None:
            raise RuntimeError(f"无法访问主贴: {entry_url}")
        soup = BeautifulSoup(resp.text, "lxml")
        h1 = soup.select_one("h1.main-title")
        raw = h1.get_text(strip=True) if h1 else ""
        book_name, _ = self._parse_title(raw)
        book_name = book_name or "未知书名"
        author = self._author_from_title(raw)
        root_tid = self._tid_of(entry_url)

        content = self._content_div(soup) or ""
        # h1 常写「…作者：xx」，但也有的书 h1 不带「作者：」→ 回退到正文头部的「作者：xx」
        if author == "未知作者":
            author = self._author_from_content(content) or author
        root_chapters = self._split_content(content, (book_name,))
        if root_tid:
            self._split_cache[root_tid] = root_chapters
            self._tid_subject[root_tid] = raw

        # 作者在正文里维护的列表链接
        list_links = self._extract_list_links(content)
        # 跟贴中的章节帖
        replies = self._fetch_replies(session, entry_url, config)

        # 抓取列表链接 + 跟贴帖子的正文并切章（按序，带礼貌延迟）
        for tid, subj in list_links + replies:
            if tid in self._split_cache:
                continue
            url = self._dir_base(entry_url) + f"index.php?app=forum&act=threadview&tid={tid}"
            self._tid_subject[tid] = subj
            print(f"  抓取帖子 {tid}  ({subj[:40]}...)")
            subj_book = (self._parse_title(subj) or (None, None))[0]
            subj_rng = (self._parse_title(subj) or (None, None))[1]
            _, nums = self._range_info(subj_rng) if subj_rng else ("", [])
            chs = self._fetch_and_split(session, url, config, (book_name, subj_book),
                                        self._single_num(subj), self._num_prefix(subj),
                                        nums, bool(subj_rng and "外传" in subj_rng), subj_rng,
                                        section_subject=subj if _SECTION_SUBJECT_RE.match(subj) else "")
            self._split_cache[tid] = chs

        chapters = self._build_chapters()
        return {"book_name": book_name, "author": author, "chapters": chapters}

    def _from_search(self, session, entry_url, config):
        """模式 D：搜索页逐页聚合，按关键词过滤 + 作者分组。

        支持两种搜索入口：
        - bbs4/index.php?...threadsearch...&keywords=…  （站内搜索，ul.post-list.thread-list）
        - search.php?keyword=…&sa=…                    （全站搜索，div.search-content ul；
          每个 <a> 第一行是版块名，第二行才是【书名】（范围）作者）
        """
        keyword = self._search_keyword(entry_url)
        items = []          # [(帖子URL, tid, subject)]
        page_url = entry_url
        seen = set()
        while page_url:
            if page_url in seen:
                break
            seen.add(page_url)
            self._polite_sleep(config)
            resp = self._get(session, page_url, config)
            if resp is None:
                break
            soup = BeautifulSoup(resp.text, "lxml")
            ul = soup.select_one("ul.post-list.thread-list") or soup.select_one("div.search-content ul")
            page_items = []
            if ul:
                for a in ul.select("a[href*='tid=']"):
                    tid = self._tid_of(a.get("href", ""))
                    subj = self._subject_of(a)
                    url = self._resolve(entry_url, a.get("href", ""))
                    if url and tid and subj:
                        page_items.append((url, tid, subj))
            items.extend(page_items)
            if not page_items:
                break                     # 空页停止
            # 下一页：threadsearch 用 a.next；search.php 用数字分页（?p=N）
            nxt = None
            a_next = soup.select_one("a.next")
            if a_next and a_next.get("href"):
                nxt = self._resolve(entry_url, a_next["href"])
            else:
                cur_m = re.search(r'[?&]p=(\d+)', page_url)
                cur_p = int(cur_m.group(1)) if cur_m else 1
                max_p = 0
                for pg in soup.select("a[href*='p=']"):
                    m = re.search(r'[?&]p=(\d+)', pg.get("href", ""))
                    if m:
                        max_p = max(max_p, int(m.group(1)))
                if cur_p < max_p:
                    base_url = re.sub(r'[?&]p=\d+', '', page_url) if cur_m else page_url
                    sep = '&' if '?' in base_url else '?'
                    nxt = f"{base_url}{sep}p={cur_p + 1}"
            page_url = nxt

        # 过滤：标题含关键词 + 章节格式
        kept = []
        for url, tid, subj in items:
            if not self._looks_like_chapter(subj):
                continue
            if keyword and keyword not in subj:
                continue
            kept.append((url, tid, subj))

        # 按作者分组（同一关键词可能混入别本书，不能静默取最大组）
        groups = {}
        for url, tid, subj in kept:
            author = self._author_from_title(subj) or "未知作者"
            groups.setdefault(author, []).append((url, tid, subj))
        if not groups:
            raise RuntimeError("搜索结果中没有找到符合格式的小说章节帖，请检查关键词/入口 URL。")

        author = self._search_author(entry_url)
        if author:
            # 用户用 &author= 指定了作者 → 精确过滤，避免下错书
            matched = None
            for key, grp in groups.items():
                if key == author or author in key or key in author:
                    matched = grp
                    break
            if matched is None:
                raise RuntimeError(
                    f"搜索结果中没有作者「{author}」的帖子（实际作者: {', '.join(groups)}）。"
                    "请检查 URL 里的 &author= 是否写对。")
            group = matched
            print(f"  已按 &author={author} 限定，匹配 {len(group)} 个帖子")
        elif len(groups) == 1:
            group = next(iter(groups.values()))
            print(f"  搜索结果匹配 {len(group)} 个帖子（作者: {next(iter(groups))}）")
        else:
            # 多个作者组 → 打印候选清单并停止，让用户补 &author= 后重跑
            lines = ["搜索命中多本书，无法自动确定你要哪一本，可选作者："]
            order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
            for i, (key, grp) in enumerate(order, 1):
                sample = "、".join(subj[:26] for _, _, subj in grp[:3])
                lines.append(f"  {i}. 作者「{key}」· {len(grp)} 帖 · 如: {sample}")
            lines.append("请把作者名拼到 URL 后面再重跑，例如: …&author=作者名")
            raise RuntimeError("\n".join(lines))

        # 抓取每个帖子的正文并切章（直接用搜索结果里的完整链接）
        for url, tid, subj in group:
            if tid in self._split_cache:
                continue
            self._tid_subject[tid] = subj
            book_name_hint, subj_rng = self._parse_title(subj) or (None, None)
            _, nums = self._range_info(subj_rng) if subj_rng else ("", [])
            print(f"  抓取帖子 {tid}  ({subj[:40]}...)")
            chs = self._fetch_and_split(session, url, config, (book_name_hint or "",),
                                        self._single_num(subj), self._num_prefix(subj),
                                        nums, bool(subj_rng and "外传" in subj_rng), subj_rng)
            self._split_cache[tid] = chs

        chapters = self._build_chapters()
        # 书名取「最小章节号所在帖子」的标题名（通常是最早发布、带最新书名的主贴）
        book_name = "未知书名"
        if chapters:
            first_tid = chapters[0].get("tid")
            subj = self._tid_subject.get(first_tid, "")
            bn, _ = self._parse_title(subj)
            if bn:
                book_name = bn
        author = self._author_from_title(self._tid_subject.get(chapters[0].get("tid"), "")) \
            if chapters else "未知作者"
        return {"book_name": book_name, "author": author, "chapters": chapters}

    @staticmethod
    def _similar_text(a, b):
        """判断两段正文是否为重复内容（节选/重发）。

        a/b 为去空白文本。规则：较短者是较长者的子串（节选/预告），
        或两者长度接近且相似度极高（近乎重发）。
        """
        if not a or not b:
            return False
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        if short in long:
            return True
        ratio = len(short) * 1.0 / len(long)
        if len(short) < 100 and ratio < 0.1:
            return True     # 极短占位（如“【未完待续】”）→ 视为重复，保留完整版
        if ratio >= 0.85:
            return difflib.SequenceMatcher(None, a, b).ratio() >= 0.97
        return False

    def _build_chapters(self):
        """合并 _split_cache 全部切章结果。

        排序：按“帖子发布时间”（tid 升序 + 帖内顺序）——作者章节号经常随心所欲
        （如 12-13 之后是 2.1-2.3），不能按章节号排序。
        去重：同一章节号多版本时，仅当内容高度相似（节选/重发）才保留最长版本；
        卷号不同的同号章节（第2.1章 vs 第1章）视为不同章，都保留。
        """
        candidates = []   # (key, tid, in_thread_idx, score, title, body, norm)
        for tid, chs in self._split_cache.items():
            for idx, (num, title, body) in enumerate(chs):
                norm = re.sub(r'\s|<[^>]+>', '', body)
                candidates.append((str(num), str(tid), idx, len(norm), title, body, norm))

        # 同章节号分组，组内按内容相似度去重（保留最完整版本）
        groups = {}
        for c in candidates:
            groups.setdefault(c[0], []).append(c)
        kept = []
        for items in groups.values():
            if len(items) == 1:
                kept.append(items[0])
                continue
            items.sort(key=lambda x: x[3], reverse=True)   # 长 → 短
            survivors = []
            for item in items:
                if any(self._similar_text(item[6], s[6]) for s in survivors):
                    continue
                survivors.append(item)
            kept.extend(survivors)

        # 按发布时间排序：主线按 tid 升序 + 帖内顺序；外传单章排在主线之后
        def _wz_key(k):
            return 1 if str(k).startswith("外传") else 0
        kept.sort(key=lambda x: (_wz_key(x[0]), int(x[1]) if x[1].isdigit() else 0, x[2]))

        chapters = []
        for i, (key, tid, _idx, _score, title, _body, _norm) in enumerate(kept):
            url = ""
            if tid:
                url = f"https://www.cool18.com/bbs4/index.php?app=forum&act=threadview&tid={tid}"
            chapters.append({
                "index": i,
                "num": key,
                "title": title,
                "tid": tid,
                "url": url,
            })
        return chapters

    # ---------------- 章节正文 ----------------

    def download_chapter(self, session, chapter, config, referer=""):
        """从切章缓存取章节正文（抓取阶段已完成，不重复请求）。"""
        tid = chapter.get("tid")
        target = str(chapter.get("num", ""))
        for num, title, body in self._split_cache.get(tid, []):
            if str(num) == target:
                html_out = self._to_paragraphs(body)
                if not html_out:
                    return False, None, None, False
                return True, html_out, title, False
        return False, None, None, False
