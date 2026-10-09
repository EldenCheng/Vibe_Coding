"""http-download（HTTP 直链文件）适配器。

产物是**平铺的文件**（不是带 progress.json 的目录），因此：
- 定位产物：解析下载器 stdout 的固定锚点行「文件保存到: <路径>」（见 http-download 设计文档 §7）；
- 状态判定：读输出目录 `.progress/` 下的 sidecar（记录 bytes_done/bytes_total/status/sha256）；
- 扫描列表：列出输出根目录下的普通文件，跳过 .part/.seg/.corrupt/.sha256 等工作文件。
"""
import re
from pathlib import Path

from .base import (Adapter, DownloadItem, LaunchPlan, STATUS_COMPLETED, STATUS_FAILED,
                   STATUS_UNVERIFIED, human_size, read_json)

# 下载器 stdout 的固定锚点行（多行模式，对整份日志文本做搜索）
SAVED_RE = re.compile(r"^文件保存到:\s*(.+?)\s*$", re.M)
PROGRESS_RE = re.compile(r"^进度文件:\s*(.+?)\s*$", re.M)

_MB = 1024 * 1024


class HttpDownloadAdapter(Adapter):
    type_id = "http"
    display_name = "HTTP 直链"

    # proxy 刻意不遮罩（用户决定，与其它下载器一致：遮罩会导致代理无法从 UI 清空）；
    # headers 里的授权类字段遮罩。
    sensitive_paths = ["headers.Authorization", "headers.Cookie"]

    form_schema = [
        {"key": "url", "label": "直链 URL", "type": "text", "required": True,
         "placeholder": "https://github.com/owner/repo/releases/download/v1/file.zip",
         "help": "必填。HTTP(S) 直链；302 跳转与 Content-Disposition 文件名都能处理"},
        {"key": "filename", "label": "保存文件名", "type": "text",
         "help": "可选。留空自动解析（Content-Disposition 优先于 URL basename）"},
        {"key": "sha256", "label": "校验值（SHA256/MD5）", "type": "text",
         "help": "可选。64 位 hex=SHA256，32 位 hex=MD5；下载完成后自动核对，不匹配会保留 .corrupt 文件"},
    ]

    config_schema_data = [
        {"key": "output_dir", "label": "输出根目录", "type": "text",
         "help": "文件平铺在该目录下。相对路径按 http-download 目录解析（默认 Download）"},
        {"key": "proxy", "label": "代理", "type": "text",
         "help": "如 http://127.0.0.1:10808。留空并保存=清空该设置。"
                 "清空不等于直连：requests 会转而读取操作系统代理"},
        {"key": "headers", "label": "请求头(JSON)", "type": "json",
         "help": "附加到每个请求，如 Referer/User-Agent；Authorization/Cookie 属敏感字段，保存后不回显"},
        {"key": "concurrency", "label": "分块并发数", "type": "number",
         "help": "1=单流；>1 且服务器支持 Range 时按段并行（上限 16）"},
        {"key": "min_split_mb", "label": "分块最小文件(MB)", "type": "number",
         "help": "小于该值的文件不分块，直接单流"},
        {"key": "speed_limit_kb", "label": "限速(KB/s)", "type": "number",
         "help": "0=不限速；多线程共享这个总口径"},
        {"key": "timeout", "label": "超时(秒)", "type": "number"},
        {"key": "retry.max_attempts", "label": "单请求最大重试", "type": "number"},
        {"key": "retry.backoff_base", "label": "重试退避基数(秒)", "type": "number"},
        {"key": "retry.backoff_multiplier", "label": "重试退避倍率", "type": "number"},
        {"key": "overwrite", "label": "重名处理", "type": "select",
         "options": ["rename", "overwrite", "skip"],
         "help": "rename=自动加序号；overwrite=覆盖旧文件；skip=跳过不下载"},
        {"key": "auto_verify", "label": "自动读同名 .sha256 校验", "type": "bool",
         "help": "输出目录存在 <文件名>.sha256（sha256sum 格式）时，下载后自动核对"},
    ]

    # ---- 配置 ----

    def config_schema(self):
        return self.config_schema_data

    def default_output_dir(self):
        return "Download"

    def output_root(self):
        """优先用管理器配置里的 output_dir；否则读下载器自己 config.json 的 output_dir。

        与 e_download 同款逻辑：下载器默认值是 "Download"（相对其项目目录），
        这里必须保持一致，否则下载列表会看不到实际产物。
        """
        raw = (self.cfg["projects"].get(self.type_id, {}) or {}).get("output_dir") or ""
        if raw.strip():
            p = Path(raw).expanduser()
            return p if p.is_absolute() else (self.project_dir / p)
        own = read_json(self.project_dir / "config.json") or {}
        value = (own.get("output_dir") or self.default_output_dir()).strip() or "."
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.project_dir / p)

    # ---- 命令构造 ----

    def _base_cmd(self):
        from .. import config as manager_config
        py, _ = manager_config.resolve_python(self.cfg)
        return [py, "-u", str(self.project_dir / "http_download.py")]

    def build_launch(self, form):
        url = (form.get("url") or "").strip()
        if not url:
            raise ValueError("请填写直链 URL")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")

        argv = self._base_cmd() + ["--output-dir", str(self.output_root())]
        sha = (form.get("sha256") or "").strip()
        if sha:
            argv += ["--sha256", sha]
        name = (form.get("filename") or "").strip()
        if name:
            argv += ["--filename", name]
        argv.append(url)

        return LaunchPlan(argv, self.project_dir, kind="download",
                          base_dir=self.output_root(),
                          note="支持断点续传：中断后重跑同一 URL 会自动续传")

    def build_action(self, action, target):
        """目前只支持 retry = 对同一 URL 重跑（下载器自己会利用 .part/段文件续传）。"""
        if action != "retry":
            raise ValueError(f"不支持的操作: {action}")
        url = (target or {}).get("url") or ""
        if not url:
            raise ValueError("缺少 URL，无法续传（请在标签页里重新填写并提交一次）")
        argv = self._base_cmd() + ["--output-dir", str(self.output_root()), url]
        return LaunchPlan(argv, self.project_dir, kind="retry", base_dir=self.output_root(),
                          note="重跑同一 URL：已下载的字节会被自动续传利用")

    def available_actions(self, item=None):
        return [{"action": "retry", "label": "续传/重下",
                 "help": "对同一个 URL 重跑一次；.part 与分块残留会被自动续传利用"}]

    # ---- 定位与状态 ----

    @staticmethod
    def is_item_dir(path):
        """产物是文件不是目录；.progress 不是产物，避免被目录差集误认。"""
        return path.name != ".progress"

    def locate_from_log(self, bus):
        """从日志缓冲里找「文件保存到: <路径>」——这是文件型产物最可靠的定位方式。"""
        for line in reversed(bus.snapshot(tail=400)):
            m = SAVED_RE.search(line.get("text", ""))
            if m:
                p = Path(m.group(1).strip())
                if p.exists():
                    return p
        return None

    def find_by_identity(self, plan):
        """按 URL 反查 sidecar 里记录的产物文件路径（服务重启后 finalize 的兜底）。"""
        url = ""
        for arg in reversed(getattr(plan, "argv", None) or []):
            if isinstance(arg, str) and arg.lower().startswith(("http://", "https://")):
                url = arg
                break
        if not url:
            return None
        for data in self._sidecars().values():
            if data.get("url") == url:
                p = Path(data.get("path") or "")
                if p.exists():
                    return p
        return None

    def _sidecars(self):
        """读输出根目录 .progress/ 下所有 sidecar，返回列表。"""
        out = []
        for root in self.scan_roots():
            pd = Path(root) / ".progress"
            if not pd.is_dir():
                continue
            for j in sorted(pd.glob("*.json")):
                data = read_json(j)
                if data:
                    out.append(data)
        return out

    def _sidecar_for(self, file_path):
        """给一个产物文件找它的 sidecar（先按完整路径匹配，再按文件名兜底）。"""
        if file_path is None:
            return None
        for data in self._sidecars():
            if data.get("path") == str(file_path):
                return data
        for data in self._sidecars():
            if data.get("file") == file_path.name:
                return data
        return None

    @staticmethod
    def _progress_dict(data, file_path=None):
        """把 sidecar 数据整理成前端进度条要的形状。

        done/total 用 MB（1 位小数）方便进度条与排序；小文件给 summary 文本；
        失败时 done 置空、summary 放错误原因（前端会原样显示）。
        """
        if not data:
            return {"done": None, "total": None, "failed": None, "status": "unknown",
                    "failed_items": [], "unit": "", "summary": "无进度记录"}
        total_b = data.get("bytes_total") or 0
        done_b = data.get("bytes_done") or 0
        status = data.get("status")
        if status == "complete":
            mapped = STATUS_COMPLETED
        elif status == "failed":
            mapped = STATUS_FAILED
        else:
            mapped = "in_progress"
        if total_b >= _MB:
            done, total, unit = round(done_b / _MB, 1), round(total_b / _MB, 1), "MB"
            summary = ""
        else:
            done, total, unit = None, None, ""
            summary = f"{human_size(done_b)} / {human_size(total_b)}"
        failed = 1 if status == "failed" else 0
        if status == "failed" and data.get("error"):
            summary = str(data["error"])
        return {"done": done, "total": total, "failed": failed, "failed_items": [],
                "status": mapped, "unit": unit, "summary": summary,
                "url": data.get("url") or "", "file": data.get("file") or "",
                "sha256": data.get("actual_sha256") or ""}

    def finalize(self, plan, exit_code, log_text=""):
        """按 stdout 锚点行 + sidecar 判定任务结果（绝不只看退出码）。"""
        text = log_text or ""
        file_path = None
        m = SAVED_RE.search(text)
        if m:
            p = Path(m.group(1).strip())
            if p.exists():
                file_path = p
        data = None
        m = PROGRESS_RE.search(text)
        if m:
            data = read_json(m.group(1).strip())
        if data is None and file_path is not None:
            data = self._sidecar_for(file_path)
        if data is None:
            # 锚点缺失（如服务重启后重判）：按 URL 反查
            file_path = file_path or self.find_by_identity(plan)
            if file_path is not None:
                data = self._sidecar_for(file_path)

        progress = self._progress_dict(data, file_path)
        target = str(file_path) if file_path else None

        if exit_code != 0:
            err = (data or {}).get("error") or ""
            msg = f"进程异常退出（退出码 {exit_code}）" + (f"：{err}" if err else "，详见输出日志")
            return {"status": STATUS_FAILED, "message": msg, "progress": progress,
                    "target_dir": target}

        status = (data or {}).get("status")
        if status == "complete":
            note = (data or {}).get("note") or ""
            size_text = human_size((data or {}).get("bytes_total") or 0)
            msg = f"完成，共 {size_text}" + (f"，{note}" if note else "")
            return {"status": STATUS_COMPLETED, "message": msg, "progress": progress,
                    "target_dir": target}
        if status == "failed":
            msg = (data or {}).get("error") or "下载失败，详见输出日志"
            return {"status": STATUS_FAILED, "message": msg, "progress": progress,
                    "target_dir": target}
        if file_path is not None and file_path.exists():
            return {"status": STATUS_UNVERIFIED,
                    "message": "进程正常结束，但进度文件未标记完成，无法核实",
                    "progress": progress, "target_dir": target}
        return {"status": STATUS_UNVERIFIED,
                "message": "进程正常结束，但未找到产物文件", "progress": progress,
                "target_dir": target}

    # ---- 扫描 ----

    def scan(self):
        """列出输出根目录下的产物文件（平铺），状态来自 sidecar。"""
        items = []
        by_path, by_name = {}, {}
        for data in self._sidecars():
            if data.get("path"):
                by_path[data["path"]] = data
            if data.get("file"):
                by_name.setdefault(data["file"], data)
        seen = set()
        for root in self.scan_roots():
            if not root.exists():
                continue
            try:
                children = sorted(root.iterdir(), key=lambda p: p.name)
            except OSError:
                continue
            for f in children:
                try:
                    if not f.is_file():
                        continue
                    name = f.name
                    # 跳过工作文件：断点/分块残留/坏数据/校验 sidecar/隐藏文件
                    if (name.startswith(".") or name.endswith((".part", ".corrupt", ".sha256"))
                            or ".part.seg" in name or name.endswith(".tmp")):
                        continue
                    real = str(f.resolve())
                    if real in seen:
                        continue
                    seen.add(real)
                    data = by_path.get(real) or by_path.get(str(f)) or by_name.get(name) or {}
                    prog = self._progress_dict(data, f)
                    items.append(DownloadItem(
                        item_id=real,
                        name=name,
                        path=f,
                        kind="文件",
                        progress=prog,
                        extra={"url": (data or {}).get("url", ""),
                               "sha256": (data or {}).get("actual_sha256", "")},
                    ))
                except OSError:
                    continue
        return items
