"""e-download（E-Hentai 画廊）适配器。"""
import json
import re
from pathlib import Path

from .base import (Adapter, DownloadItem, LaunchPlan, STATUS_COMPLETED, STATUS_FAILED,
                   STATUS_PARTIAL, STATUS_UNVERIFIED, read_json)

# 画廊 URL 形如 https://e-hentai.org/g/<gid>/<token>/
GALLERY_RE = re.compile(r"https?://[^/]+/g/(\d+)/([0-9a-fA-F]+)")


class EDownloadAdapter(Adapter):
    type_id = "ehentai"
    display_name = "E-Hentai 画廊"

    # 注意：proxy 刻意不列入敏感字段（用户决定）—— 各下载工具历来都把代理当普通配置，
    # 遮罩它反而导致「已设置时留空=不修改」，在 UI 上根本没法把代理清空。
    # 代价：若代理 URL 里带 user:pass@，它会以明文出现在页面上（局域网 HTTP，无 TLS）。
    sensitive_paths = ["cookies", "headers.Authorization", "headers.Cookie"]

    form_schema = [
        {"key": "url", "label": "画廊 URL", "type": "text", "required": True,
         "placeholder": "https://e-hentai.org/g/3743290/8eee725d8c/",
         "help": "必填。形如 https://e-hentai.org/g/<编号>/<token>/，token 必须是十六进制"},
        {"key": "range", "label": "下载页码范围", "type": "text", "placeholder": "1-10,20,30-40",
         "help": "可选。留空=下载全部；支持区间与逗号分隔，页码从 1 开始。已下载的页会自动跳过"},
    ]

    config_schema_data = [
        {"key": "output_dir", "label": "画廊输出根目录", "type": "text",
         "help": "画廊目录会建在这个目录下。相对路径按 e-download 目录解析（默认 Download）"},
        {"key": "proxy", "label": "代理", "type": "text",
         "help": "如 http://127.0.0.1:10808。留空并保存=清空该设置。"
                 "清空不等于直连：requests 会转而读取操作系统代理"
                 "（Windows 注册表 Internet 设置 / macOS 网络设置）"},
        {"key": "use_mpv", "label": "启用 MPV API", "type": "bool",
         "help": "游客访问 MPV 会返回 eeenope，默认关闭"},
        {"key": "request_delay.min", "label": "每页最小等待(秒)", "type": "float",
         "help": "每页下载前的随机等待下限。调太小容易触发站点限流"},
        {"key": "request_delay.max", "label": "每页最大等待(秒)", "type": "float"},
        {"key": "retry.max_attempts", "label": "单页最大重试次数", "type": "number"},
        {"key": "retry.backoff_base", "label": "重试退避基数(秒)", "type": "number"},
        {"key": "retry.backoff_multiplier", "label": "重试退避倍率", "type": "number"},
        {"key": "timeout_page", "label": "页面超时(秒)", "type": "number"},
        {"key": "timeout_image", "label": "图片超时(秒)", "type": "number"},
        {"key": "headers", "label": "请求头(JSON)", "type": "json"},
        {"key": "cookies", "label": "登录 Cookie(JSON)", "type": "json",
         "help": "需要登录才能看的画廊要填 ipb_member_id / ipb_pass_hash。留空表示不修改"},
    ]

    # ---- 配置 ----

    def config_schema(self):
        return self.config_schema_data

    def default_output_dir(self):
        return "Download"

    def output_root(self):
        """优先用管理器配置里的 output_dir；否则用下载器自己 config.json 的 output_dir。

        注意下载器默认值是 "Download"（相对其项目目录），所以这里必须与它保持一致，
        否则管理器的下载列表会看不到任务实际写入的位置。
        """
        raw = (self.cfg["projects"].get(self.type_id, {}) or {}).get("output_dir") or ""
        if raw.strip():
            p = Path(raw).expanduser()
            return p if p.is_absolute() else (self.project_dir / p)
        own = read_json(self.project_dir / "config.json") or {}
        value = (own.get("output_dir") or self.default_output_dir()).strip() or "."
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.project_dir / p)

    def scan_roots(self):
        """输出根目录 + 历史遗留的 Download/ 目录（旧版本曾把产物写在那里）。"""
        roots = [self.output_root()]
        legacy = self.project_dir / "Download"
        if legacy.exists() and legacy.resolve() != roots[0].resolve():
            roots.append(legacy)
        # 旧版本还把画廊直接放在项目根目录，也一并扫描
        if self.project_dir.exists() and self.project_dir.resolve() != roots[0].resolve():
            roots.append(self.project_dir)
        return roots

    # ---- 命令行 ----

    def _base_cmd(self):
        from .. import config as manager_config
        py, _ = manager_config.resolve_python(self.cfg)
        return [py, "-u", str(self.project_dir / "download_gallery.py")]

    def build_launch(self, form):
        url = (form.get("url") or "").strip()
        if not url:
            raise ValueError("请填写画廊 URL")
        if not GALLERY_RE.search(url):
            raise ValueError("画廊 URL 格式不正确，应为 https://e-hentai.org/g/<编号>/<token>/")

        argv = self._base_cmd()
        range_text = (form.get("range") or "").strip()
        if form.get("mode") == "retry":
            argv.append("--rd")
        argv += ["--output-dir", str(self.output_root())]
        if range_text:
            argv += ["--range", range_text]
        argv.append(url)

        note = ""
        if range_text:
            note = f"仅下载范围内尚未完成的页（{range_text}）"
        return LaunchPlan(argv, self.project_dir, kind="download",
                          base_dir=self.output_root(), note=note)

    def build_action(self, action, target):
        url = (target or {}).get("url") or (target or {}).get("id_url")
        if not url:
            url = (target or {}).get("gallery_url")
        if not url:
            raise ValueError("缺少画廊 URL，无法执行该操作（请在标签页里重新填写并下载一次）")

        argv = self._base_cmd() + ["--output-dir", str(self.output_root())]
        if action == "check":
            argv.append("--check")
            kind = "check"
        elif action == "retry":
            argv.append("--rd")
            kind = "retry"
        else:
            raise ValueError(f"不支持的操作: {action}")
        argv.append(url)

        plan = LaunchPlan(argv, self.project_dir, kind=kind, base_dir=self.output_root())
        plan.target_hint = (target or {}).get("name")
        return plan

    def available_actions(self, item=None):
        actions = [{"action": "check", "label": "校验(check)",
                    "help": "扫描 images/ 实际文件，把缺失页写入 failed（需要联网）"},
                   {"action": "retry", "label": "重下失败页(rd)",
                    "help": "只重试 progress.json 中 failed 列表里的页"}]
        return actions

    # ---- 定位与状态 ----

    @staticmethod
    def _is_gallery_dir(path):
        return (path / "progress.json").exists() or (path / "images").is_dir()

    @staticmethod
    def is_item_dir(path):
        return (path / "progress.json").exists() or (path / "images").is_dir()

    def find_by_identity(self, plan):
        """按画廊 gid/token 反查已有目录。

        重跑一个已经下载过的画廊时不会产生新目录，快照差集找不到目标；
        但 progress.json 里记着 gid 与 gallery_url，可以据此精确匹配。
        """
        argv = getattr(plan, "argv", None) or []
        url = ""
        for arg in reversed(argv):
            if isinstance(arg, str) and GALLERY_RE.search(arg):
                url = arg
                break
        if not url:
            return None
        match = GALLERY_RE.search(url)
        if not match:
            return None
        gid = match.group(1)
        for root in self.scan_roots():
            if not root.exists():
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir() or not self._is_gallery_dir(child):
                        continue
                    data = read_json(child / "progress.json") or {}
                    if str(data.get("gid") or "") == gid:
                        return child
            except OSError:
                continue
        return None

    def locate_from_log(self, bus):
        """从日志里找“图片保存在: <路径>”这一行，这是最可靠的定位方式。"""
        for line in reversed(bus.snapshot(tail=400)):
            m = re.search(r"图片保存在:\s*(.+?)\s*$", line.get("text", ""))
            if m:
                p = Path(m.group(1).strip())
                if p.exists():
                    return p
        return None

    def finalize(self, plan, exit_code, log_text=""):
        target = self.detect_target_dir(plan)
        if plan and plan.kind in ("check", "retry"):
            # 校验/重下是一次性动作，按退出码 + 日志结论给结果
            if exit_code != 0:
                return {"status": STATUS_FAILED, "message": "操作失败，详见输出日志", "progress": {}}
            return {"status": STATUS_COMPLETED, "message": "操作完成，详见输出日志", "progress": {}}

        if target is None:
            if exit_code == 0:
                return {"status": STATUS_UNVERIFIED,
                        "message": "进程正常结束，但未找到画廊目录，无法核实结果", "progress": {}}
            return {"status": STATUS_FAILED, "message": f"进程异常退出（退出码 {exit_code}）", "progress": {}}

        data = read_json(target / "progress.json") or {}
        downloaded = data.get("downloaded") or []
        failed = data.get("failed") or []
        total = data.get("total") or 0
        progress = {
            "done": len(downloaded),
            "total": total,
            "failed": len(failed),
            "failed_items": sorted(failed)[:200],
            "unit": "页",
            "dir": str(target),
        }
        if exit_code != 0:
            return {"status": STATUS_FAILED, "message": f"进程异常退出（退出码 {exit_code}）",
                    "progress": progress, "target_dir": str(target)}
        if failed:
            return {"status": STATUS_PARTIAL,
                    "message": f"完成 {len(downloaded)}/{total} 页，{len(failed)} 页失败，可用「重下失败页」补下",
                    "progress": progress, "target_dir": str(target)}
        if total and len(downloaded) >= total:
            return {"status": STATUS_COMPLETED,
                    "message": f"全部完成，共 {total} 页", "progress": progress,
                    "target_dir": str(target)}
        return {"status": STATUS_UNVERIFIED,
                "message": f"进程正常结束（进度 {len(downloaded)}/{total}），但未标记为完成",
                "progress": progress, "target_dir": str(target)}

    # ---- 扫描 ----

    def _progress_of(self, path):
        data = read_json(path / "progress.json")
        if not data:
            return {"done": None, "total": None, "failed": None, "status": "unknown",
                    "failed_items": [], "unit": "页"}
        downloaded = data.get("downloaded") or []
        failed = data.get("failed") or []
        total = data.get("total") or 0
        if failed:
            status = STATUS_PARTIAL
        elif total and len(downloaded) >= total:
            status = STATUS_COMPLETED
        else:
            status = "in_progress"
        return {
            "done": len(downloaded),
            "total": total,
            "failed": len(failed),
            "failed_items": sorted(failed)[:200],
            "status": status,
            "unit": "页",
            "title": data.get("title") or path.name,
            "gallery_url": data.get("gallery_url") or "",
        }

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
                    if not self._is_gallery_dir(child):
                        continue
                    real = str(child.resolve())
                    if real in seen:
                        continue
                    seen.add(real)
                    prog = self._progress_of(child)
                    items.append(DownloadItem(
                        item_id=real,
                        name=prog.get("title") or child.name,
                        path=child,
                        kind="画廊",
                        progress=prog,
                        extra={"url": prog.get("gallery_url", "")},
                    ))
                except OSError:
                    continue
        return items
