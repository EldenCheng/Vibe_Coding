"""REST API 路由与 SSE 事件流。

接口一览见设计文档 §11。约定：
- 所有写操作要求令牌（由 httpd 层统一校验）
- 错误统一返回 {"error": {"code", "message"}}，HTTP 状态码语义正确
"""
import json
import time
from pathlib import Path

from . import config as manager_config
from . import config_store
from . import fso
from . import sysinfo
from .httpd import Response
from .logbus import sse_pack
from .adapters import build_adapters
from .task_manager import TaskManager

# 版本号：单一来源在 backend/config.py，与 版本变更.md 保持一致
VERSION = manager_config.VERSION
APP_NAME = "统一下载管理器"


class Services:
    """把适配器与任务管理器组装在一起，配置变更时可整体重建适配器。"""

    def __init__(self):
        self.cfg = manager_config.get_config()
        self.adapters = build_adapters(self.cfg)
        self.tasks = TaskManager(self.cfg, self.adapters)

    def reload_config(self):
        self.cfg = manager_config.get_config(reload=True)
        self.adapters = build_adapters(self.cfg)
        self.tasks.cfg = self.cfg
        self.tasks.adapters = self.adapters
        # 队列键随适配器重建而对齐
        for type_id in self.adapters:
            self.tasks.queues.setdefault(type_id, __import__("collections").deque())
        return self.cfg

    def adapter(self, type_id):
        adapter = self.adapters.get(type_id)
        if adapter is None:
            raise LookupError(f"未知的下载器类型: {type_id}")
        return adapter

    def adapter_meta(self):
        """给前端用的适配器元信息（参数表单、配置表单、可用操作）。"""
        out = []
        for type_id, adapter in self.adapters.items():
            try:
                probe = adapter.probe()
            except Exception as exc:
                probe = {"ok": False, "problems": [str(exc)]}
            out.append({
                "type": type_id,
                "name": adapter.display_name,
                "project_dir": str(adapter.project_dir),
                "output_root": str(adapter.output_root()),
                "form_schema": adapter.form_schema,
                "available_actions": adapter.available_actions(),
                "probe": probe,
            })
        return out


def register_routes(router, services: Services):
    """把所有路由挂到 router 上。"""

    # ---------------------------------------------------------- 基础

    @router.get("/api/health", auth=False)
    def health(_req):
        return {"ok": True, "name": APP_NAME, "version": VERSION}

    @router.get("/api/sysinfo")
    def get_sysinfo(_req):
        return sysinfo.collect(services.adapters, services.tasks)

    @router.get("/api/adapters")
    def list_adapters(_req):
        return {"adapters": services.adapter_meta()}

    # ---------------------------------------------------------- 系统 / 文件管理器

    @router.post("/api/system/open")
    def system_open(req):
        """在**后端本机**的文件管理器中打开一个目录/文件（v0.2.0）。

        路径必须位于某个下载器的输出根/扫描根之内，避免这个接口被当成任意路径浏览器。
        """
        body = req.json() or {}
        raw = (body.get("path") or "").strip()
        select = bool(body.get("select"))
        if not raw:
            return Response.error("缺少 path 参数", 400, "bad_request")
        if not fso.supported():
            return Response.error("后端平台不支持打开文件管理器", 400, "unsupported")
        path = Path(raw).expanduser()
        if not path.exists():
            return Response.error(f"路径不存在: {raw}", 404, "not_found")
        if not _is_trusted_path(path, services):
            return Response.error("只允许打开下载器输出目录范围内的路径", 403, "forbidden")
        ok, message = fso.open_path(path, select=select)
        if not ok:
            return Response.error(message, 500, "open_failed")
        return {"ok": True, "path": str(path), "message": message,
                "opener": fso.opener_name()}

    # ---------------------------------------------------------- 配置

    @router.get("/api/adapters/<type_id>/config")
    def get_config(req):
        type_id = req.route_params["type_id"]
        adapter = services.adapter(type_id)
        try:
            raw = config_store.load_raw(adapter.project_dir)
        except config_store.ConfigError as exc:
            return Response.error(str(exc), 400, "config_error")
        described = config_store.describe(raw, adapter.config_schema(),
                                         adapter.sensitive_paths)
        described["path"] = str(adapter.project_dir / "config.json")
        described["backups"] = [b.name for b in config_store.backup_paths(adapter.project_dir)][:10]
        described["exists"] = (adapter.project_dir / "config.json").exists()
        return described

    @router.put("/api/adapters/<type_id>/config")
    def put_config(req):
        type_id = req.route_params["type_id"]
        adapter = services.adapter(type_id)
        patch = req.json() or {}
        try:
            result = config_store.apply_patch(adapter.project_dir, patch,
                                             adapter.config_schema(),
                                             adapter.sensitive_paths)
        except config_store.ConfigError as exc:
            return Response.error(str(exc), 400, "config_invalid")
        # 输出目录可能被改了，同步刷新管理器侧缓存
        result["output_root"] = str(adapter.output_root())
        return result

    @router.post("/api/adapters/<type_id>/config/restore")
    def restore_config(req):
        type_id = req.route_params["type_id"]
        adapter = services.adapter(type_id)
        name = (req.json() or {}).get("name")
        try:
            restored = config_store.restore_backup(adapter.project_dir, name)
        except config_store.ConfigError as exc:
            return Response.error(str(exc), 400, "config_error")
        return {"restored": restored}

    # ---------------------------------------------------------- 任务

    @router.post("/api/tasks")
    def create_task(req):
        body = req.json() or {}
        type_id = (body.get("type") or "").strip()
        kind = (body.get("kind") or "download").strip()
        form = body.get("form") or {}
        try:
            services.adapter(type_id)
        except LookupError as exc:
            return Response.error(str(exc), 404, "unknown_type")
        try:
            task = services.tasks.create_task(type_id, kind, form)
        except ValueError as exc:
            return Response.error(str(exc), 400, "invalid_form")
        except Exception as exc:
            return Response.error(f"创建任务失败: {exc}", 500, "internal_error")
        return {"task": task.to_dict()}

    @router.get("/api/tasks")
    def list_tasks(req):
        type_id = req.arg("type")
        limit = req.arg("limit")
        return {"tasks": services.tasks.list_tasks(type_id, int(limit) if limit else None)}

    @router.get("/api/tasks/<task_id>")
    def get_task(req):
        task = services.tasks.get(req.route_params["task_id"])
        if task is None:
            return Response.error("任务不存在", 404, "not_found")
        return {"task": task.to_dict()}

    @router.post("/api/tasks/<task_id>/stop")
    def stop_task(req):
        try:
            task = services.tasks.stop(req.route_params["task_id"])
        except ValueError as exc:
            return Response.error(str(exc), 400, "invalid_state")
        return {"task": task.to_dict()}

    @router.delete("/api/tasks/<task_id>")
    def remove_task(req):
        try:
            services.tasks.remove(req.route_params["task_id"])
        except ValueError as exc:
            return Response.error(str(exc), 400, "invalid_state")
        return {"ok": True}

    @router.get("/api/tasks/<task_id>/log")
    def task_log(req):
        task = services.tasks.get(req.route_params["task_id"])
        if task is None:
            return Response.error("任务不存在", 404, "not_found")
        bus = services.tasks.logs.get(task.id)
        after = req.arg("after")
        tail = req.arg("tail")
        if bus is not None:
            lines = bus.snapshot(after_seq=int(after or 0), tail=int(tail) if tail else None)
        else:
            # 服务重启后内存里没有该任务，从日志文件补读尾部
            lines = _read_log_file(task.log_path, int(tail or 500))
        return {"task_id": task.id, "lines": lines,
                "last_seq": lines[-1]["seq"] if lines else int(after or 0)}

    @router.get("/api/tasks/<task_id>/events", streaming=True)
    def task_events(req):
        """SSE：推送该任务的日志行与状态变化。"""
        task_id = req.route_params["task_id"]
        task = services.tasks.get(task_id)

        def gen():
            after = int(req.arg("after") or 0)
            bus = services.tasks.logs.get(task_id)
            last_status = None
            # 首屏把已有日志补齐
            if bus is not None:
                for line in bus.snapshot(after_seq=after):
                    after = max(after, line["seq"])
                    yield sse_pack("log", line)
            yield sse_pack("hello", {"task_id": task_id})
            deadline = time.time() + 3600 * 6   # 单连接最长 6 小时，前端会自动重连
            while time.time() < deadline:
                current = services.tasks.get(task_id)
                if current is not None and current.status != last_status:
                    last_status = current.status
                    yield sse_pack("status", current.to_dict())
                if bus is None:
                    bus = services.tasks.logs.get(task_id)
                if bus is not None:
                    lines = bus.wait_for_lines(after, timeout=20)
                    for line in lines:
                        after = max(after, line["seq"])
                        yield sse_pack("log", line)
                    if not lines:
                        yield sse_pack("heartbeat", {"ts": time.time()})
                else:
                    yield sse_pack("heartbeat", {"ts": time.time()})
                    time.sleep(2)
                cur = services.tasks.get(task_id)
                if cur is not None and cur.status not in ("running", "queued") and bus is not None \
                        and bus.last_seq <= after:
                    # 任务已结束且日志已全部发出，收尾
                    yield sse_pack("done", {"status": cur.status})
                    return

        return gen()

    @router.get("/api/events", streaming=True)
    def global_events(req):
        """SSE：全局任务事件（用于完成通知与标题计数）。"""
        def gen():
            after = 0
            for item in services.tasks.events_since(after):
                after = item["seq"]
                yield sse_pack(item["event"], item["data"])
            yield sse_pack("hello", {"ts": time.time()})
            deadline = time.time() + 3600 * 6
            while time.time() < deadline:
                items = services.tasks.wait_events(after, timeout=20)
                if not items:
                    yield sse_pack("heartbeat", {"ts": time.time()})
                    continue
                for item in items:
                    after = max(after, item["seq"])
                    yield sse_pack(item["event"], item["data"])
        return gen()

    # ---------------------------------------------------------- 下载列表

    @router.get("/api/downloads/<type_id>")
    def scan_downloads(req):
        """扫描该下载器的输出目录（只在用户点刷新时被调用）。"""
        type_id = req.route_params["type_id"]
        try:
            adapter = services.adapter(type_id)
        except LookupError as exc:
            return Response.error(str(exc), 404, "unknown_type")
        try:
            items = adapter.scan()
        except Exception as exc:
            return Response.error(f"扫描失败: {exc}", 500, "scan_error")
        return {
            "type": type_id,
            "roots": [str(r) for r in adapter.scan_roots()],
            "items": [i.to_dict() for i in items],
            "scanned_at": time.time(),
        }

    @router.post("/api/downloads/<type_id>/action")
    def download_action(req):
        """对某个产物执行 check / retry / build_epub / resume。"""
        type_id = req.route_params["type_id"]
        try:
            adapter = services.adapter(type_id)
        except LookupError as exc:
            return Response.error(str(exc), 404, "unknown_type")
        body = req.json() or {}
        action = (body.get("action") or "").strip()
        target = body.get("target") or {}
        try:
            task = services.tasks.create_task(type_id, action, {"target": target})
        except ValueError as exc:
            return Response.error(str(exc), 400, "invalid_action")
        except Exception as exc:
            return Response.error(f"创建任务失败: {exc}", 500, "internal_error")
        return {"task": task.to_dict()}

    @router.get("/api/downloads/<type_id>/detail")
    def download_detail(req):
        """查看单个产物的进度明细（失败章节/页码列表）。"""
        type_id = req.route_params["type_id"]
        try:
            adapter = services.adapter(type_id)
        except LookupError as exc:
            return Response.error(str(exc), 404, "unknown_type")
        path = req.arg("path")
        if not path:
            return Response.error("缺少 path 参数", 400, "bad_request")
        p = Path(path)
        if not p.exists():
            return Response.error("目录不存在", 404, "not_found")
        if type_id == "ebook":
            return {"detail": adapter.progress_of_dir(p)}
        if type_id == "video":
            return {"detail": adapter.progress_of_dir(p)}
        # e-hentai
        from .adapters.base import read_json
        if type_id == "http":
            # 文件型产物：从 .progress sidecar 里按 path 匹配进度记录
            side = p.parent / ".progress"
            if side.is_dir():
                for j in sorted(side.glob("*.json")):
                    d = read_json(j) or {}
                    if d.get("path") == str(p):
                        return {"detail": {
                            "title": d.get("file") or p.name,
                            "total": d.get("bytes_total"),
                            "downloaded": d.get("bytes_done"),
                            "failed": 1 if d.get("status") == "failed" else 0,
                            "status": d.get("status"),
                            "note": d.get("note"),
                            "error": d.get("error"),
                            "url": d.get("url"),
                            "sha256": d.get("actual_sha256"),
                        }}
            return {"detail": {"title": p.name, "status": "unknown"}}
        data = read_json(p / "progress.json") or {}
        return {"detail": {
            "title": data.get("title"), "total": data.get("total"),
            "downloaded": len(data.get("downloaded") or []),
            "failed": sorted(data.get("failed") or [])[:500],
            "gallery_url": data.get("gallery_url"),
        }}


def _is_trusted_path(path, services):
    """判断 path 是否落在某个下载器的扫描根/输出根之内。"""
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    for adapter in services.adapters.values():
        roots = []
        try:
            roots.extend(adapter.scan_roots())
        except Exception:
            pass
        try:
            roots.append(adapter.output_root())
        except Exception:
            pass
        for root in roots:
            try:
                root_res = Path(root).resolve()
            except OSError:
                continue
            if target == root_res or root_res in target.parents:
                return True
    return False


def _read_log_file(path, tail=500):
    """从日志文件读最后 N 行，转成与内存日志一致的格式。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for i, text in enumerate(lines[-tail:], start=1):
        out.append({"seq": i, "ts": 0, "kind": "out", "text": text.rstrip("\n"),
                    "overwrite": False})
    return out


def not_found(method, path):
    if path.startswith("/api/"):
        return Response.error(f"接口不存在: {method} {path}", 404, "not_found")
    # 非 API 路径返回前端入口，交给前端路由（本项目只有一个页面）
    return None


def on_error(exc, traceback_text):
    import traceback as tb
    tb.print_exc()
    return Response.error(f"服务器内部错误: {exc}", 500, "internal_error")
