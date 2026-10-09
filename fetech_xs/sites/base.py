"""站点适配器基类：每个站点实现「怎么拿章节表」和「怎么拿章节正文」。

公共部分（进度断点续传、重试退避、请求延迟、文件保存、EPUB 生成）由
download_novel.py 统一处理；本模块只定义站点侧需要实现的接口与共享工具。
"""
import copy


class SiteAdapter:
    """站点适配器抽象基类。"""

    type_id = ""            # 站点标识（日志/分发用）
    domains = []            # 匹配的 host 片段（小写比较，`in` 判断）
    site_key = ""           # config.json 里 sites.<site_key> 覆盖段的键名

    def __init__(self, config):
        self.config = config or {}

    # ---- 匹配与配置 ----

    @classmethod
    def matches(cls, url):
        low = (url or "").lower()
        return any(d in low for d in cls.domains)

    def site_config(self):
        """全局配置 + sites.<site_key> 覆盖合并。

        合并规则：dict 字段与全局对应字段浅层合并，标量字段直接覆盖。
        未配置 sites 段的站点得到的就是全局配置本身。
        """
        merged = copy.deepcopy(self.config)
        over = (self.config.get("sites") or {}).get(self.site_key) or {}
        for key, value in over.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    # ---- 站点侧必须实现的接口 ----

    def resolve_entry(self, session, entry, config):
        """把 book_id / URL 规整成入口 URL。默认原样返回（传入即 URL）。"""
        return entry

    def fetch_book_info(self, session, entry_url, config):
        """从入口 URL 获取书籍信息，返回：
        {book_name, author, chapters: [ {index, title, url, ...} ]}
        chapters 的 index 为 0 基顺序号（即最终章节顺序，EPUB 按此排序）。
        实现方负责把需要的正文抓全并切好（cool18 在这里抓全部帖子并缓存切章结果）。
        """
        raise NotImplementedError

    def download_chapter(self, session, chapter, config, referer=""):
        """下载单个章节正文，返回 (ok, html, title, fetched)。

        - ok: 是否成功；False 时由入口统一退避重试
        - html: 章节正文 HTML（<p> 段落结构）
        - title: 章节标题（可能比 fetch_book_info 里的更完整，如小标题）
        - fetched: 是否真正发了网络请求（True → 入口在章节间 sleep 礼貌延迟；
          False → 数据来自缓存，不 sleep）
        """
        raise NotImplementedError
