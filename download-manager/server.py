"""服务入口：读配置 → 建应用 → 起 HTTP 服务 → 起后台线程。

用法：
    py server.py                 # 用 config.json 里的 host/port
    py server.py --port 9000     # 临时换端口
    py server.py --host 127.0.0.1  # 只允许本机访问
    py server.py --force         # 跳过单实例检查（仅测试等特殊场景）

为什么用标准库的 http.server 而不是 Flask：
本机 pip 在当前环境无法访问 PyPI，且三个下载器都只依赖标准库。用标准库的额外好处是
长期运行时依赖面为零（没有框架与 C 扩展的版本风险），与「服务长期不重启」的需求一致。
并发由 ThreadingHTTPServer + 有界线程池提供，SSE 长连接不会阻塞其他请求。
"""
import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path

# 允许从任意 cwd 启动
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import config as manager_config          # noqa: E402
from backend import runner                            # noqa: E402
from backend import sysinfo                           # noqa: E402
from backend.app import Services, register_routes, not_found, on_error   # noqa: E402
from backend.auth import check_request                 # noqa: E402
from backend.httpd import App, Response                # noqa: E402
from backend.instance_lock import InstanceLock         # noqa: E402

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


# ---------------------------------------------------------------- 防休眠

class SleepGuard:
    """按配置阻止系统休眠。

    下载任务可能连续跑 8~10 小时，系统休眠会直接中断网络与进程。
    macOS 用 caffeinate（系统自带），Windows 用 SetThreadExecutionState（ctypes）。
    平台不支持时只打印一行日志，不影响服务。
    """

    def __init__(self, enabled):
        self.enabled = enabled
        self.proc = None
        self._win_handle = None
        self.detail = "未启用"

    def acquire(self):
        if not self.enabled:
            return
        if sys.platform == "darwin":
            self._acquire_macos()
        elif os.name == "nt":
            self._acquire_windows()
        else:
            self.detail = f"{sys.platform} 平台不支持自动防休眠"

    def _acquire_macos(self):
        import shutil
        import subprocess
        exe = shutil.which("caffeinate")
        if not exe:
            self.detail = "未找到 caffeinate 命令"
            return
        try:
            # -i 阻止空闲休眠；-w <pid> 绑定到本进程，服务退出即释放
            self.proc = subprocess.Popen([exe, "-i", "-w", str(os.getpid())],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            self.detail = "已通过 caffeinate 阻止空闲休眠"
        except OSError as exc:
            self.detail = f"caffeinate 启动失败: {exc}"

    def _acquire_windows(self):
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            # 返回上一次的状态；ES_CONTINUOUS 表示一直生效直到再次调用复位
            self._win_handle = ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            self.detail = "已通过 SetThreadExecutionState 阻止系统休眠"
        except Exception as exc:
            self.detail = f"设置防休眠失败: {exc}"

    def release(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None
        if self._win_handle:
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass
            self._win_handle = None


# ---------------------------------------------------------------- 网络工具

def local_ips():
    """本机的局域网 IPv4 地址列表（用于打印访问地址）。"""
    ips = []
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    # 兜底：连一个外部地址看本机出口 IP（不会真的发包）
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return ips


def _port_listening(host, port, timeout=0.6):
    """连接探测：端口上有人在监听就返回 True。

    比 bind 探测可靠：不受 SO_REUSEADDR 语义影响。
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            if sock.connect_ex(sockaddr) == 0:
                return True
        except OSError:
            pass
        finally:
            sock.close()
    return False


def check_port(host, port):
    """启动前检查端口是否真的可用，给出明确错误而不是抛栈。

    **不能用 bind + SO_REUSEADDR 探测**：Windows 的 SO_REUSEADDR 允许绑定一个
    已被别人**主动监听**的端口（语义接近 Unix 的 SO_REUSEPORT），于是探测永远成功、
    第二个管理器照样启动，两个实例又各自覆盖 data/tasks.json（设计文档 §20.12）。
    现在分两步：
      1) 连接探测：能连上就说明有人在监听 → 直接判定占用；
      2) 独占绑定探测：Windows 下**不设** SO_REUSEADDR（并尽量用 SO_EXCLUSIVEADDRUSE），
         POSIX 下保留它以避免 TIME_WAIT 造成的误报（POSIX 的它不会抢占活跃监听）。
    """
    probe_host = host if host not in ("", "0.0.0.0", "::") else "127.0.0.1"
    if _port_listening(probe_host, port):
        return False, f"{probe_host}:{port} 上已经有服务在监听"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return True, ""
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()


def print_banner(cfg, guard):
    server = cfg["server"]
    token = server["access_token"]
    host = server["host"]
    port = server["port"]
    py, py_src = manager_config.resolve_python(cfg)

    print("=" * 68)
    print(f"  统一下载管理器 v{manager_config.VERSION}")
    print("=" * 68)
    print(f"  监听地址 : {host}:{port}")
    print(f"  访问令牌 : {token}")
    print()
    print("  浏览器打开下列任一地址（首次会带上令牌，前端会记住，之后直接输地址即可）：")
    if host in ("127.0.0.1", "localhost"):
        print(f"    http://127.0.0.1:{port}/?token={token}")
    else:
        for ip in local_ips():
            print(f"    http://{ip}:{port}/?token={token}")
        print(f"    http://127.0.0.1:{port}/?token={token}   (本机)")
    print()
    print(f"  Python   : {py}  ({py_src})")
    print(f"  防休眠   : {guard.detail}")
    for type_id, adapter in SERVICES.adapters.items():
        try:
            probe = adapter.probe()
            mark = "OK  " if probe.get("ok") else "问题"
            print(f"  [{mark}] {adapter.display_name}: {probe.get('project_dir')}")
            for problem in probe.get("problems", []):
                print(f"         - {problem}")
        except Exception as exc:
            print(f"  [问题] {adapter.display_name}: 自检异常 {exc}")
    print()
    print("  提示：令牌写在 download-manager/config.json 的 server.access_token，可随时更换。")
    print("  Ctrl+C 停止服务（正在运行的任务不会被自动杀掉，重启后可在页面续跑）。")
    print("=" * 68)
    sys.stdout.flush()


# ---------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(description="统一下载管理器")
    parser.add_argument("--host", default=None, help="覆盖配置里的监听地址")
    parser.add_argument("--port", type=int, default=None, help="覆盖配置里的端口")
    parser.add_argument("--no-sleep-guard", action="store_true", help="本次不阻止系统休眠")
    parser.add_argument("--force", action="store_true",
                        help="跳过单实例检查（仅供测试或确有需要时使用）")
    parser.add_argument("--open", "--web", dest="open_browser", action="store_true",
                        help="启动后在默认浏览器打开管理界面（地址已带访问令牌）")
    args = parser.parse_args()

    cfg = manager_config.load_config()
    if args.host:
        cfg["server"]["host"] = args.host
    if args.port:
        cfg["server"]["port"] = args.port

    host = cfg["server"]["host"]
    port = int(cfg["server"]["port"])
    token = cfg["server"]["access_token"]

    global SERVICES
    SERVICES = Services()
    SERVICES.cfg = cfg

    ok, err = check_port(host, port)
    if not ok:
        print(f"[错误] 无法监听 {host}:{port} —— {err}")
        print("       端口可能已被占用（改 config.json 的 server.port，或用 --port 指定）")
        return 1

    # 单实例锁：即使端口检查被绕过（或用户手动换了端口），也不允许第二个实例
    # 和当前实例共用 data/tasks.json —— 两个实例会互相覆盖任务记录。
    lock = InstanceLock()
    ok, message = lock.acquire(host, port, force=args.force)
    if not ok:
        print(f"[错误] {message}")
        print("       同一时间只允许一个管理器实例：两个实例会互相覆盖任务记录。")
        print("       请先关掉那个实例；若确认它是异常退出残留的，"
              f"删除 {lock.path} 后重试（或用 --force）。")
        return 1
    if message:
        print(f"[单实例] {message}")

    guard = SleepGuard(cfg.get("sleep_guard", {}).get("enabled", True)
                       and not args.no_sleep_guard)
    guard.acquire()

    app = App(auth_check=check_request, not_found=not_found, on_error=on_error)
    register_routes(app.router, SERVICES)

    # 前端静态资源（/static/css/... 、/static/js/...）
    app.router.add_static("/static/", FRONTEND_DIR)

    # 页面入口：需要令牌（未授权时前端会显示引导页）
    def serve_index(_req):
        index = FRONTEND_DIR / "index.html"
        if not index.exists():
            return Response.error("前端文件缺失：frontend/index.html", 500, "frontend_missing")
        return Response(raw=index.read_bytes(),
                        content_type="text/html; charset=utf-8")

    app.router.add("GET", "/", serve_index)
    app.router.add("GET", "/index.html", serve_index)

    # 未授权引导页（公开，不需要令牌）
    def serve_login(_req):
        page = FRONTEND_DIR / "login.html"
        if page.exists():
            return Response(raw=page.read_bytes(),
                            content_type="text/html; charset=utf-8")
        return Response.error("需要访问令牌", 401, "unauthorized")

    app.router.add("GET", "/login", serve_login, auth=False)

    def serve_favicon(_req):
        fav = FRONTEND_DIR / "favicon.ico"
        if fav.exists():
            return Response(raw=fav.read_bytes(), content_type="image/x-icon")
        return Response(status=204)

    app.router.add("GET", "/favicon.ico", serve_favicon, auth=False)

    SERVICES.tasks.start_housekeeping()
    print_banner(cfg, guard)

    # --open / --web：服务真正开始监听后再自动打开浏览器，
    # 避免打得太早、浏览器连不上。on_ready 由 App.serve_forever 在套接字建好后回调。
    on_ready = None
    if args.open_browser:
        open_url = f"http://127.0.0.1:{port}/?token={token}"

        def _open_browser():
            try:
                import webbrowser
                if not webbrowser.open(open_url):
                    print(f"[提示] 未能自动打开浏览器，请手动访问 {open_url}")
            except Exception as exc:  # 无桌面环境/无默认浏览器时不应影响服务
                print(f"[提示] 自动打开浏览器失败：{exc}")

        on_ready = lambda: threading.Thread(target=_open_browser, daemon=True).start()
        print(f"[浏览器] 将自动打开：{open_url}")
        sys.stdout.flush()

    # 后台预热一次系统信息（探测量 Python/ffmpeg/playwright，首次较慢）
    threading.Thread(target=lambda: sysinfo.collect(SERVICES.adapters, SERVICES.tasks),
                     daemon=True).start()

    try:
        app.serve_forever(host, port, on_ready=on_ready)
    except KeyboardInterrupt:
        print("\n[退出] 收到 Ctrl+C，正在保存任务记录...")
    finally:
        lock.release()
        guard.release()
        SERVICES.tasks.shutdown()
        app.shutdown()
        print("[退出] 已停止。正在运行的下载进程不会被自动结束，"
              "下次启动时会在页面提示并可续跑。")
    return 0


SERVICES = None


if __name__ == "__main__":
    sys.exit(main())
