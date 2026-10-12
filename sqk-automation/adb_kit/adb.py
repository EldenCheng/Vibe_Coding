"""adb 命令封装：连接、查询、shell、截图。

所有调用统一走参数列表 + shell=False，避免命令注入。
"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .config import Device, Settings

PNG_MAGIC = b"\x89PNG"
PNG_END = b"IEND\xaeB`\x82"
REMOTE_TMP = "/sdcard/sqk_screenshot.png"


class AdbError(RuntimeError):
    """adb 调用失败。"""


class ScreencapUnsupported(AdbError):
    """exec-out 通道拿不到完整 PNG，需改走 pull 兼容路径。"""


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    """执行一条完整 adb 命令（args 已含可执行文件路径）。"""
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, shell=False)
    except FileNotFoundError as exc:
        raise AdbError(
            f"找不到可执行文件 {args[0]!r}。\n"
            f"请安装 Android platform-tools 并加入 PATH，"
            f"或在 config/devices.json 的 adb_path 里填写绝对路径。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"命令超时（{timeout}s）：{' '.join(args)}") from exc


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").strip()


def run_adb(settings: Settings, *args: str, timeout: int = 30) -> str:
    """执行 adb 命令并要求成功，返回 stdout 文本。"""
    result = _run([settings.adb_path, *args], timeout=timeout)
    if result.returncode != 0:
        raise AdbError(_format_failure(list(args), result))
    return _text(result.stdout)


def run_shell(settings: Settings, device: Device, command: str, timeout: int = 30) -> str:
    """在指定设备上执行 shell 命令。"""
    return run_adb(settings, "-s", device.serial, "shell", command, timeout=timeout)


def _format_failure(args: list, result: subprocess.CompletedProcess) -> str:
    """把 adb 的原始错误整理成带排查方向的提示。"""
    out, err = _text(result.stdout), _text(result.stderr)
    detail = err or out or f"退出码 {result.returncode}"

    hint = ""
    joined = f"{out}\n{err}".lower()
    if "unauthorized" in joined:
        hint = "\n可能原因：盒子屏幕上还没点『允许 USB 调试』。"
    elif "cannot connect" in joined or "refused" in joined or "offline" in joined:
        hint = (
            "\n可能原因：盒子已关机 / 换了 IP / 无线调试掉线。"
            "\n排查：核对 config/devices.json 里的 IP → 在盒子上重新开启网络调试"
            "（必要时先用 USB 连一次执行 adb tcpip 5555）。"
        )
    elif "device not found" in joined:
        hint = "\n可能原因：连接尚未建立或已失效，先跑 py main.py run connect。"

    return f"adb {' '.join(args)} 失败：{detail}{hint}"


def check_adb(settings: Settings) -> None:
    """启动前确认 adb 可执行，避免后续每条命令都失败一遍。"""
    if shutil.which(settings.adb_path) or Path(settings.adb_path).exists():
        return
    raise AdbError(
        f"本机找不到 adb：{settings.adb_path!r}\n"
        f"请安装 Android platform-tools 并加入 PATH，"
        f"或在 config/devices.json 的 adb_path 里填写绝对路径。"
    )


def ensure_server(settings: Settings) -> None:
    """确保本机 adb server 已启动。"""
    run_adb(settings, "start-server", timeout=20)


def connect(settings: Settings, device: Device) -> str:
    """建立无线连接，返回一句人话描述。"""
    check_adb(settings)
    ensure_server(settings)
    result = _run(
        [settings.adb_path, "connect", device.serial],
        timeout=settings.connect_timeout,
    )
    text = (_text(result.stdout) + "\n" + _text(result.stderr)).strip()
    lowered = text.lower()

    if "already connected" in lowered:
        return f"{device.serial} 已在连接列表中。"
    if "connected" in lowered:
        return text
    if result.returncode == 0:
        raise AdbError(f"连接 {device.serial} 未成功：{text or '无输出'}")
    raise AdbError(_format_failure(["connect", device.serial], result))


def list_serials(settings: Settings) -> list:
    """返回当前 adb 已识别、可执行命令的设备 serial 列表。"""
    ensure_server(settings)
    output = run_adb(settings, "devices", timeout=20)
    serials = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def is_connected(settings: Settings, device: Device) -> bool:
    return device.serial in list_serials(settings)


def wait_online(settings: Settings, device: Device, seconds: int = 10) -> bool:
    """轮询等待设备进入可命令状态。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if is_connected(settings, device):
            return True
        time.sleep(0.5)
    return False


def device_info(settings: Settings, device: Device) -> dict:
    """读取设备基本信息，用于确认连上的是不是预期的盒子。"""
    probes = {
        "型号": "getprop ro.product.model",
        "安卓版本": "getprop ro.build.version.release",
        "分辨率": "wm size",
    }
    info = {}
    for key, cmd in probes.items():
        try:
            info[key] = run_shell(settings, device, cmd, timeout=10) or "读不到"
        except AdbError:
            info[key] = "未知"
    return info


def screencap_exec_out(settings: Settings, device: Device) -> bytes:
    """首选截图方式：exec-out 直接取回 PNG 字节流。

    必须以二进制接收——文本模式会做换行转换，破坏 PNG。
    """
    args = ["-s", device.serial, "exec-out", "screencap", "-p"]
    result = _run([settings.adb_path, *args], timeout=30)
    if result.returncode != 0:
        raise AdbError(_format_failure(args, result))

    data = _repair_png(result.stdout)
    if data is None:
        raise ScreencapUnsupported(
            f"exec-out 未取回完整 PNG（收到 {len(result.stdout)} 字节）"
        )
    return data


def _repair_png(raw: bytes) -> bytes | None:
    """从 exec-out 输出里切出合法 PNG；无法还原时返回 None。"""
    start = raw.find(PNG_MAGIC)
    if start < 0:
        return None
    body = raw[start:]

    # 部分设备的通道会把 \n 展开成 \r\n，靠 PNG 签名头判断是否被展开过
    if body.startswith(b"\x89PNG\r\r\n"):
        body = body.replace(b"\r\n", b"\n")

    end = body.rfind(PNG_END)
    return body[: end + len(PNG_END)] if end >= 0 else None


def screencap_via_pull(settings: Settings, device: Device) -> bytes:
    """兼容截图方式：先在设备上落文件，再 pull 回来。"""
    run_shell(settings, device, f"screencap -p {REMOTE_TMP}")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "shot.png"
            run_adb(settings, "-s", device.serial, "pull", REMOTE_TMP, str(local), timeout=30)
            data = local.read_bytes()
    finally:
        try:
            run_shell(settings, device, f"rm {REMOTE_TMP}", timeout=10)
        except AdbError:
            pass  # 远端清理失败不影响本次截图结果

    if not data.startswith(PNG_MAGIC):
        raise AdbError("拉回的文件不是合法 PNG，该设备可能不支持 screencap。")
    return data


def capture(settings: Settings, device: Device) -> bytes:
    """抓取设备屏幕，返回 PNG 字节。"""
    ensure_server(settings)
    try:
        return screencap_exec_out(settings, device)
    except ScreencapUnsupported:
        return screencap_via_pull(settings, device)
