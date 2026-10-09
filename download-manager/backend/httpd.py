"""极简 HTTP 框架（纯标准库）。

为什么不用 Flask：本机 pip 在当前沙箱下无法访问 PyPI，且三个下载器都只需要标准库。
用标准库的额外好处是长期运行时的依赖面为零 —— 不会有框架版本、C 扩展、
第三方库升级带来的意外，这与「服务要长期不重启」的需求是一致的。

提供的能力刚好够这个项目的需要：
- 路径参数路由（/api/tasks/<id>/stop）
- JSON 请求体与响应
- 静态文件
- 线程池并发（SSE 会长期占用连接，所以必须有并发能力）
- 统一的错误响应
"""
import json
import mimetypes
import os
import re
import socket
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, unquote, urlparse

# 单个任务需要的并发不高：页面 + 若干 SSE 流，16 个线程足够
MAX_WORKERS = 16


class Request:
    """一次请求的上下文。"""

    __slots__ = ("method", "path", "params", "query", "headers", "body", "remote", "route_params")

    def __init__(self, method, path, params, query, headers, body, remote):
        self.method = method
        self.path = path
        self.params = params            # 路由里的路径参数
        self.query = query              # ?a=1 → {"a": ["1"]}
        self.headers = headers
        self.body = body                # 已解析的 JSON（或 {}）
        self.remote = remote
        self.route_params = params

    # ---- 便于视图读取的小工具 ----

    def json(self):
        return self.body

    def arg(self, name, default=None):
        vals = self.query.get(name)
        return vals[0] if vals else default

    def header(self, name, default=""):
        return self.headers.get(name.lower(), default)

    def get(self, name, default=None):
        """从 body 取值（body 只能是 dict 时才有意义）。"""
        if isinstance(self.body, dict):
            return self.body.get(name, default)
        return default


class Response:
    """视图返回值的封装。"""

    def __init__(self, status=200, body=None, content_type="application/json; charset=utf-8",
                 headers=None, raw=None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.headers = headers or {}
        self.raw = raw          # 已是 bytes 时直接发送（静态文件/SSE 不适用）

    @classmethod
    def json(cls, data, status=200):
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        return cls(status=status, raw=payload, content_type="application/json; charset=utf-8")

    @classmethod
    def error(cls, message, status=400, code="bad_request"):
        return cls.json({"error": {"code": code, "message": message}}, status=status)


class Router:
    """按 (方法, 路径模板) 注册视图。路径模板用 <name> 表示参数。"""

    def __init__(self):
        self._routes = []
        self._static_dirs = []

    def add(self, method, pattern, view, auth=True, streaming=False):
        regex = "^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", pattern) + "$"
        self._routes.append({
            "method": method.upper(),
            "pattern": pattern,
            "regex": re.compile(regex),
            "view": view,
            "auth": auth,
            "streaming": streaming,
        })

    def route(self, method, pattern, auth=True, streaming=False):
        def deco(fn):
            self.add(method, pattern, fn, auth=auth, streaming=streaming)
            return fn
        return deco

    def get(self, pattern, auth=True, streaming=False):
        return self.route("GET", pattern, auth=auth, streaming=streaming)

    def post(self, pattern, auth=True):
        return self.route("POST", pattern, auth=auth)

    def put(self, pattern, auth=True):
        return self.route("PUT", pattern, auth=auth)

    def delete(self, pattern, auth=True):
        return self.route("DELETE", pattern, auth=auth)

    def add_static(self, url_prefix, directory):
        self._static_dirs.append((url_prefix, os.path.abspath(directory)))

    def match(self, method, path):
        """返回 (route, 路径参数) 或 (None, None)。"""
        for r in self._routes:
            if r["method"] != method.upper():
                continue
            m = r["regex"].match(path)
            if m:
                return r, m.groupdict()
        return None, None

    def match_static(self, path):
        for prefix, directory in self._static_dirs:
            if path.startswith(prefix):
                rel = unquote(path[len(prefix):]).lstrip("/")
                target = os.path.abspath(os.path.join(directory, rel))
                # 防目录穿越：解析后必须仍在静态目录内
                if target == directory or target.startswith(directory + os.sep):
                    return target
        return None


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """每个连接一个线程，但线程来自有界线程池，避免长期运行时线程无限增长。

    SSE 连接会长期占用线程，所以必须有上限；单人使用 16 个并发足够
    （页面若干请求 + 几个日志流）。
    """

    daemon_threads = True
    # Windows 上必须**关掉**地址复用：SO_REUSEADDR 在 Windows 的语义允许重复绑定一个
    # 正在被别人监听的端口（接近 Unix 的 SO_REUSEPORT），会让两个管理器实例同时对外服务、
    # 并互相覆盖 data/tasks.json。POSIX 上它只影响 TIME_WAIT，不会抢占活跃监听，保留 True。
    allow_reuse_address = os.name != "nt"
    request_queue_size = 32

    def __init__(self, address, handler, executor):
        self._executor = executor
        super().__init__(address, handler)

    def server_bind(self):
        # Windows 专用加固：显式声明独占该端口，杜绝任何形式的重复绑定
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()

    def process_request(self, request, client_address):
        self._executor.submit(self._process_request_thread, request, client_address)

    def _process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # 浏览器刷新/关掉输出页签时会在读请求行阶段直接断开连接。
            # 这是正常现象，不该往控制台喷 20 行 traceback。
            pass
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def _make_handler(router, auth_check, not_found, on_error):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "DownloadManager/0.1"

        # ---- 日志：默认会打到 stderr，这里改成安静模式（管理器自己有日志） ----
        def log_message(self, fmt, *args):
            return

        # ---- 请求入口 ----

        def _read_body(self):
            length = self.headers.get("Content-Length")
            if not length:
                return {}
            try:
                size = int(length)
            except ValueError:
                return {}
            if size <= 0 or size > 32 * 1024 * 1024:
                return {}
            data = self.rfile.read(size)
            try:
                return json.loads(data.decode("utf-8", errors="replace"))
            except ValueError:
                return {}

        def _build_request(self, params):
            parsed = urlparse(self.path)
            return Request(
                method=self.command,
                path=unquote(parsed.path),
                params=params,
                query=parse_qs(parsed.query),
                headers={k.lower(): v for k, v in self.headers.items()},
                body=self._read_body(),
                remote=self.client_address[0] if self.client_address else "",
            )

        def _send(self, response):
            body = response.raw
            if body is None:
                body = json.dumps(response.body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _handle(self, method):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            # 静态文件
            static_target = router.match_static(path)
            if static_target is not None:
                return self._serve_static(static_target)

            route, params = router.match(method, path)
            if route is None:
                return self._send(not_found(method, path))

            request = self._build_request(params)

            # 鉴权（公开路由由 auth_check 自己判断）
            if route["auth"]:
                denied = auth_check(request)
                if denied is not None:
                    return self._send(denied)

            try:
                if route["streaming"]:
                    return self._serve_stream(route["view"], request)
                result = route["view"](request)
                if result is None:
                    result = Response.json({"ok": True})
                elif not isinstance(result, Response):
                    result = Response.json(result)
                return self._send(result)
            except ClientDisconnected:
                return
            except Exception as exc:  # 单个请求出错不能拖垮服务
                return self._send(on_error(exc, traceback.format_exc()))

        # ---- 静态文件 ----

        def _serve_static(self, target):
            if not os.path.isfile(target):
                return self._send(Response.error("文件不存在", 404, "not_found"))
            ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            try:
                with open(target, "rb") as fh:
                    body = fh.read()
            except OSError as exc:
                return self._send(Response.error(f"读取文件失败: {exc}", 500, "io_error"))
            return self._send(Response(raw=body, content_type=ctype))

        # ---- SSE 流式响应 ----

        def _serve_stream(self, view, request):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                for chunk in view(request):
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                raise ClientDisconnected()

        # ---- HTTP 动词 ----

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

        def do_HEAD(self):
            self._handle("HEAD")

    return Handler


class ClientDisconnected(Exception):
    """客户端在流式响应中途断开。"""


class App:
    """应用外壳：路由表 + 线程池服务器。"""

    def __init__(self, auth_check, not_found, on_error):
        self.router = Router()
        self.auth_check = auth_check
        self.not_found = not_found
        self.on_error = on_error
        self._server = None
        self._executor = None

    def serve_forever(self, host, port, on_ready=None):
        handler = _make_handler(self.router, self.auth_check, self.not_found, self.on_error)
        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS,
                                            thread_name_prefix="http")
        self._server = _ThreadedHTTPServer((host, port), handler, self._executor)
        # 套接字已监听后再回调（例如 --open 自动开浏览器），避免连不上
        if on_ready is not None:
            try:
                on_ready()
            except Exception:
                pass
        self._server.serve_forever()

    def shutdown(self):
        if self._server:
            self._server.shutdown()
        if self._executor:
            self._executor.shutdown(wait=False)

    @property
    def server(self):
        return self._server
