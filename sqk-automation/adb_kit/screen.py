"""截图落盘：文件命名与写入 screen_shot/。"""

from datetime import datetime
from pathlib import Path

from .config import Device, Settings

TIME_FORMAT = "%Y-%m-%d_%H%M%S"


def build_filename(device: Device, device_count: int, when: datetime | None = None) -> str:
    """按『日期_时间』命名；配置了多台设备时加设备名前缀，避免同秒互相覆盖。"""
    when = when or datetime.now()
    stem = when.strftime(TIME_FORMAT)
    if device_count > 1:
        # 设备名可能含路径非法字符，做一次替换
        prefix = "".join("_" if c in '\\/:*?"<>|' else c for c in device.name)
        return f"{prefix}_{stem}.png"
    return f"{stem}.png"


def save(settings: Settings, device: Device, data: bytes, device_count: int) -> Path:
    """把 PNG 字节写入 screenshot_dir，返回最终文件路径。"""
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    target = settings.screenshot_dir / build_filename(device, device_count)
    target.write_bytes(data)
    return target
