"""fetech_xs（电子书 / EPUB）适配器。"""
import json
import re
import urllib.parse
from pathlib import Path

from .base import (Adapter, DownloadItem, LaunchPlan, STATUS_COMPLETED, STATUS_CRASHED,
                   STATUS_FAILED, STATUS_PARTIAL, STATUS_UNVERIFIED, read_json)

# 章节列表 URL 形如 .../other/chapters/id/<book_id>.html
BOOK_ID_RE = re.compile(r"/id/(\d+)")
# 章节文件名形如 0000_标题.html
CHAPTER_FILE_RE = re.compile(r"^(\d+)_")


class FetchXsAdapter(Adapter):
    type_id = "ebook"
    display_name = "电子书（fetech_xs）"

    sensitive_paths = ["base_url", "headers.Authorization", "headers.Cookie"]

    form_schema = [
        {"key": "book", "label": "book_id 或章节列表 URL", "type": "text", "required": True,
         "placeholder": "32157  或  https://.../other/chapters/id/32157.html",
         "help": "必填。填纯数字视为 book_id；也可粘贴完整的章节列表页地址"},
        {"key": "author", "label": "作者（可选，仅 cool18 搜索页）", "type": "text",
         "placeholder": "留空 = 使用原 URL",
         "help": "仅 cool18 的搜索页 URL 有效。填了作者名，提交时会自动在 URL 后拼接 "
                 "&author=作者名，用于搜索结果混入多本书时精确锁定你要的那一本。"
                 "留空则保持原 URL 不变。"},
    ]

    config_schema_data = [
        {"key": "output_dir", "label": "书籍输出根目录", "type": "text",
         "help": "书名目录会建在这里。相对路径按 fetech_xs 目录解析（默认 Download）"},
        {"key": "proxy", "label": "代理", "type": "text",
         "help": "如 http://127.0.0.1:10808。跨机使用时填代理所在机器的局域网地址"
                 "（如 http://192.168.2.100:10808，且代理软件需允许局域网连接）。"
                 "留空并保存=清空该设置，此时 requests 会转而读取操作系统代理"},
        {"key": "request_delay.min", "label": "每章最小等待(秒)", "type": "number",
         "help": "强烈建议不要调小，默认 10~15 秒是对站点友好的间隔"},
        {"key": "request_delay.max", "label": "每章最大等待(秒)", "type": "number"},
        {"key": "retry.max_attempts", "label": "单章最大重试次数", "type": "number",
         "help": "设为 1 时脚本内置的退避重试不会真正生效"},
        {"key": "retry.backoff_base", "label": "重试退避基数(秒)", "type": "number"},
        {"key": "retry.backoff_multiplier", "label": "重试退避倍率", "type": "number"},
        {"key": "headers", "label": "请求头(JSON)", "type": "json"},
    ]

    def config_schema(self):
        return self.config_schema_data

    def default_output_dir(self):
        return "Download"

    def output_root(self):
        """优先管理器配置；否则读下载器自己 config.json 的 output_dir。"""
        raw = (self.cfg["projects"].get(self.type_id, {}) or {}).get("output_dir") or ""
        if raw.strip():
            p = Path(raw).expanduser()
            return p if p.is_absolute() else (self.project_dir / p)
        own = read_json(self.project_dir / "config.json") or {}
        value = (own.get("output_dir") or self.default_output_dir()).strip() or "."
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.project_dir / p)

    def scan_roots(self):
        roots = [self.output_root()]
        # 旧版本曾把书直接放在项目根目录
        if self.project_dir.exists() and self.project_dir.resolve() != roots[0].resolve():
            roots.append(self.project_dir)
        return roots

    # ---- 命令行 ----

    def _py(self):
        from .. import config as manager_config
        py, _ = manager_config.resolve_python(self.cfg)
        return py

    def _normalize(self, raw):
        """把表单输入归一化成命令行参数，并推导预期的书名目录名（能推则推）。"""
        text = (raw or "").strip()
        if not text:
            raise ValueError("请填写 book_id 或章节列表 URL")
        if text.isdigit():
            return text, None
        if not text.startswith(("http://", "https://")):
            raise ValueError("请填写纯数字 book_id，或以 http(s):// 开头的章节列表地址")
        return text, None

    def build_launch(self, form):
        raw, _ = self._normalize(form.get("book"))
        author = (form.get("author") or "").strip()
        if author:
            # cool18 搜索页的作者限定：自动拼 &author=，避免多书歧义时下错书
            if not raw.startswith(("http://", "https://")):
                raise ValueError("「作者」需要搭配 cool18 的搜索页 URL 使用，book_id 模式不支持")
            if "cool18.com" not in raw:
                raise ValueError("「作者」限定仅适用于 cool18 的搜索页 URL")
            sep = "&" if "?" in raw else "?"
            raw = f"{raw}{sep}author={urllib.parse.quote(author)}"
        argv = [self._py(), "-u", str(self.project_dir / "download_novel.py"),
                "--output-dir", str(self.output_root())]
        if form.get("mode") == "retry":
            argv.append("--rd")
        argv.append(raw)
        return LaunchPlan(argv, self.project_dir, kind="download",
                          base_dir=self.output_root(),
                          note="命令行的 --output-dir 会覆盖 config.json 中的 output_dir")

    def build_action(self, action, target):
        name = (target or {}).get("name")
        raw = (target or {}).get("book_arg") or (target or {}).get("book_id")
        argv = [self._py(), "-u"]
        if action == "build_epub":
            if not name:
                raise ValueError("缺少书名，无法生成 EPUB")
            argv += [str(self.project_dir / "build_epub.py"),
                     "--output-dir", str(self.output_root()), name]
            plan = LaunchPlan(argv, self.project_dir, kind="build_epub",
                              base_dir=self.output_root(), target_hint=name)
            return plan
        if not raw:
            raise ValueError("缺少 book_id / URL，无法执行该操作")
        argv += [str(self.project_dir / "download_novel.py"),
                 "--output-dir", str(self.output_root())]
        if action == "check":
            argv.append("--check")
            kind = "check"
        elif action == "retry":
            argv.append("--rd")
            kind = "retry"
        else:
            raise ValueError(f"不支持的操作: {action}")
        argv.append(raw)
        plan = LaunchPlan(argv, self.project_dir, kind=kind, base_dir=self.output_root(),
                          target_hint=name)
        return plan

    def available_actions(self, item=None):
        actions = [
            {"action": "check", "label": "校验(check)",
             "help": "扫描 chapters/ 实际文件，把缺失章节写入 failed（需联网抓章节表）"},
            {"action": "retry", "label": "重下失败章节(rd)",
             "help": "只重试 progress.json 中 failed 列表里的章节"},
            {"action": "build_epub", "label": "生成 EPUB",
             "help": "扫描 chapters/ 生成 <书名>.epub"},
        ]
        if item and not (item.get("progress") or {}).get("has_titles"):
            pass
        return actions

    # ---- 定位与状态 ----

    def locate_from_log(self, bus):
        """用日志里的「输出根目录: X」+「书名: Y」组合出书籍目录。"""
        book_name = None
        root = None
        for line in bus.snapshot(tail=600):
            text = line.get("text", "")
            m = re.search(r"^书名:\s*(.+?)\s*$", text)
            if m:
                book_name = m.group(1).strip()
            m = re.search(r"^输出根目录:\s*(.+?)\s*$", text)
            if m:
                root = Path(m.group(1).strip())
        if book_name:
            cand = (root or self.output_root()) / book_name
            if cand.exists():
                return cand
        return None

    @staticmethod
    def _is_book_dir(path):
        return (path / "progress.json").exists() or (path / "chapters").is_dir()

    @staticmethod
    def is_item_dir(path):
        return (path / "progress.json").exists() or (path / "chapters").is_dir()

    def find_by_identity(self, plan):
        """按 book_id / tid / 入口 URL 反查已有书籍目录。

        重跑一本已经下载完的书时不会产生新目录，快照差集找不到目标；
        但 progress.json 里记着 chapters_url（含 book_id / cool18 的 tid 或 keywords），
        据此精确匹配（cool18 的 URL 没有 /id/ 前缀，v2.0 起按 tid/keywords 反查）。
        """
        argv = getattr(plan, "argv", None) or []
        wanted = ""            # 纯数字 book_id
        wanted_tid = ""        # cool18 帖子 tid
        wanted_kw = ""         # cool18 搜索关键词
        wanted_url = ""        # 完整入口 URL
        for arg in argv:
            if not isinstance(arg, str) or arg.startswith("-"):
                continue
            if arg.startswith(("http://", "https://")):
                wanted_url = arg
                m = re.search(r"tid=(\d+)", arg)
                if m:
                    wanted_tid = m.group(1)
                m = re.search(r"keywords=([^&]+)", arg)
                if m:
                    wanted_kw = m.group(1)
                # search.php 全站搜索用 keyword（单数）
                m = re.search(r"keyword=([^&]+)", arg)
                if m and not wanted_kw:
                    wanted_kw = m.group(1)
            elif arg.isdigit():
                wanted = arg
        if not (wanted or wanted_tid or wanted_kw or wanted_url):
            return None
        for root in self.scan_roots():
            if not root.exists():
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir() or not self._is_book_dir(child):
                        continue
                    data = read_json(child / "progress.json") or {}
                    url = str(data.get("chapters_url") or "")
                    if wanted and (f"/id/{wanted}" in url or url.endswith(wanted)):
                        return child
                    if wanted_tid and f"tid={wanted_tid}" in url:
                        return child
                    if wanted_kw and wanted_kw in url:
                        return child
                    if wanted_url and url == wanted_url:
                        return child
            except OSError:
                continue
        return None

    def _chapter_count(self, book_dir):
        chapters = book_dir / "chapters"
        if not chapters.is_dir():
            return 0
        count = 0
        try:
            for f in chapters.iterdir():
                if f.is_file() and CHAPTER_FILE_RE.match(f.name):
                    count += 1
        except OSError:
            return 0
        return count

    def progress_of_dir(self, book_dir):
        data = read_json(book_dir / "progress.json") or {}
        downloaded = data.get("downloaded") or []
        failed = data.get("failed") or []
        total = data.get("total") or len(data.get("chapter_titles") or {}) or 0
        on_disk = self._chapter_count(book_dir)
        if failed:
            status = STATUS_PARTIAL
        elif total and len(downloaded) >= total:
            status = STATUS_COMPLETED
        elif data.get("status") == "complete":
            status = STATUS_COMPLETED
        else:
            status = "in_progress"

        # 失败章节索引 → 可读标题
        titles = data.get("chapter_titles") or {}
        failed_items = []
        for idx in sorted(failed)[:200]:
            title = titles.get(str(idx)) or f"第 {idx + 1} 章"
            failed_items.append({"index": idx, "title": title})

        return {
            "done": len(downloaded),
            "total": total,
            "on_disk": on_disk,
            "failed": len(failed),
            "failed_items": failed_items,
            "status": status,
            "unit": "章",
            "book_name": data.get("book_name") or book_dir.name,
            "author": data.get("author") or "",
            "chapters_url": data.get("chapters_url") or "",
            "has_titles": bool(titles),
            "epub": str(book_dir / f"{book_dir.name}.epub")
            if (book_dir / f"{book_dir.name}.epub").exists() else "",
        }

    def finalize(self, plan, exit_code, log_text=""):
        if plan and plan.kind in ("check", "retry", "build_epub"):
            if exit_code != 0:
                extra = ""
                if plan.kind == "build_epub" and "ebooklib" in log_text:
                    extra = "（缺少 ebooklib，请先安装）"
                return {"status": STATUS_FAILED, "message": f"操作失败{extra}，详见输出日志",
                        "progress": {}}
            return {"status": STATUS_COMPLETED, "message": "操作完成，详见输出日志", "progress": {}}

        target = self.detect_target_dir(plan)
        if target is None:
            if "Traceback" in (log_text or ""):
                return {"status": STATUS_CRASHED,
                        "message": "脚本异常退出且未找到书籍目录，详见输出日志", "progress": {}}
            if exit_code == 0:
                return {"status": STATUS_UNVERIFIED,
                        "message": "进程正常结束，但未找到书籍目录，无法核实结果", "progress": {}}
            return {"status": STATUS_FAILED, "message": f"进程异常退出（退出码 {exit_code}）",
                    "progress": {}}

        prog = self.progress_of_dir(target)
        if exit_code != 0:
            # fetech_xs 单章网络超时会让整个进程崩溃（无 try 包裹），这里区分出来
            status = STATUS_CRASHED if "Traceback" in (log_text or "") else STATUS_FAILED
            msg = "脚本异常中断（常见原因：单章请求超时）" if status == STATUS_CRASHED \
                else f"进程异常退出（退出码 {exit_code}）"
            msg += f"，已下载 {prog['done']}/{prog['total']} 章，可再次运行继续"
            return {"status": status, "message": msg, "progress": prog,
                    "target_dir": str(target)}

        if prog["failed"]:
            return {"status": STATUS_PARTIAL,
                    "message": f"完成 {prog['done']}/{prog['total']} 章，{prog['failed']} 章失败，"
                               f"可用「重下失败章节」补下",
                    "progress": prog, "target_dir": str(target)}
        if prog["total"] and prog["done"] >= prog["total"]:
            return {"status": STATUS_COMPLETED,
                    "message": f"全部完成，共 {prog['done']} 章，可生成 EPUB", "progress": prog,
                    "target_dir": str(target)}
        return {"status": STATUS_UNVERIFIED,
                "message": f"进程正常结束（进度 {prog['done']}/{prog['total']}），但未标记为完成",
                "progress": prog, "target_dir": str(target)}

    # ---- 扫描 ----

    def scan(self):
        items = []
        seen = set()
        for root in self.scan_roots():
            if not root.exists():
                continue
            for child in sorted(root.iterdir(), key=lambda p: p.name):
                try:
                    if not child.is_dir() or child.name in ("__pycache__", "design", "Design"):
                        continue
                    if not self._is_book_dir(child):
                        continue
                    real = str(child.resolve())
                    if real in seen:
                        continue
                    seen.add(real)
                    prog = self.progress_of_dir(child)
                    items.append(DownloadItem(
                        item_id=real,
                        name=prog.get("book_name") or child.name,
                        path=child,
                        kind="电子书",
                        progress=prog,
                        extra={
                            "author": prog.get("author", ""),
                            "epub": prog.get("epub", ""),
                            "book_arg": prog.get("chapters_url") or child.name,
                        },
                    ))
                except OSError:
                    continue
        return items
