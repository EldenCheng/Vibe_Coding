"""爱丽丝书屋（als1004.space）适配器。

由原 download_novel.py 的相关逻辑迁入，行为保持不变，仅封装为适配器。
- 章节列表页解析：div.mu_h1 h1 / ul.mulu_list li a / /id/(数字) / /book/(数字)/
- 章节正文：HTML 方式取 div.read-content.j_readContent，失败切 AJAX 接口
- 每个章节一个独立请求（fetched=True，入口负责在章节间 sleep 礼貌延迟）
"""
import json
import re

import requests
from bs4 import BeautifulSoup

from .base import SiteAdapter

DEFAULT_TIMEOUT = 30


class AliceBookAdapter(SiteAdapter):
    type_id = "alice_book"
    domains = ["als1004.space", "xn--1jqx9a"]
    site_key = "alice_book"
    BASE = "https://xn--1jqx9a.als1004.space"

    def resolve_entry(self, session, entry, config):
        """纯数字 book_id → 拼成章节列表 URL；否则原样使用（完整 URL）。"""
        text = str(entry).strip()
        if text.isdigit():
            return f"{self.BASE}/other/chapters/id/{text}.html"
        return text

    # ---- 章节表 ----

    def fetch_book_info(self, session, entry_url, config):
        """从章节列表页提取书名/作者/book_id/source_id/全部章节。"""
        base_url = self._base_url(entry_url)
        resp = session.get(entry_url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # 书名：<div class="mu_h1"><h1>《书名》</h1>
        book_name = "未知书名"
        title_tag = soup.select_one("div.mu_h1 h1")
        if title_tag:
            raw_title = title_tag.get_text(strip=True)
            m = re.search(r"《(.+?)》", raw_title)
            book_name = m.group(1) if m else raw_title

        # 作者
        author_tag = soup.select_one("span:has(a[href*='/search/']) a")
        author = author_tag.get_text(strip=True) if author_tag else "未知作者"

        # book_id
        m = re.search(r"/id/(\d+)", entry_url)
        book_id = int(m.group(1)) if m else 0

        # source_id（首个章节链接里的 /book/{source_id}/）
        source_id = 0
        first_link = soup.select_one("ul.mulu_list li a")
        if first_link:
            m = re.search(r"/book/(\d+)/", first_link.get("href", ""))
            if m:
                source_id = int(m.group(1))

        chapters = self._extract_chapters(soup, source_id)

        # 供 download_chapter 使用
        self._base_url = base_url
        self._source_id = source_id

        return {
            "book_name": book_name,
            "author": author,
            "book_id": book_id,
            "source_id": source_id,
            "chapters": chapters,
        }

    def _extract_chapters(self, soup, source_id):
        """解析 ul.mulu_list 章节链接，过滤卷标，返回章节列表。"""
        chapters = []
        index = 0
        for li in soup.select("ul.mulu_list li"):
            a = li.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            # 跳过卷标（如"第一部 黄昏篇"），只保留正式章节
            if re.match(r'^第[^章]+[部卷篇集]', title):
                continue
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

    # ---- 章节正文 ----

    def download_chapter(self, session, chapter, config, referer=""):
        """HTML 方式下载，失败切 AJAX 接口。返回 (ok, html, title, fetched)。"""
        ok, result = self._download_html(session, chapter, referer)
        if not ok:
            ok, result = self._download_ajax(session, chapter)
        return ok, result, chapter["title"], True

    def _download_html(self, session, chapter, referer):
        """方式A：HTML 页面下载，解析 div.read-content.j_readContent。"""
        base_url = getattr(self, "_base_url", self.BASE)
        url = f"{base_url}/book/{self._source_id}/{chapter['hash']}.html"
        headers = {"Referer": referer} if referer else None
        resp = session.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        soup = BeautifulSoup(resp.text, "lxml")
        content_div = soup.select_one("div.read-content.j_readContent")
        if content_div is None:
            return False, "no content div"
        html_content = "".join(str(tag) for tag in content_div.children)
        if not html_content.strip():
            return False, "empty content"
        return True, html_content

    def _download_ajax(self, session, chapter):
        """方式B：AJAX 接口 GET /home/chapter/info?id=&key=。"""
        base_url = getattr(self, "_base_url", self.BASE)
        url = f"{base_url}/home/chapter/info"
        params = {"id": self._source_id, "key": chapter["hash"]}
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

    @staticmethod
    def _base_url(entry_url):
        m = re.search(r"(https?://[^/]+)", entry_url)
        return m.group(1) if m else "https://xn--1jqx9a.als1004.space"
