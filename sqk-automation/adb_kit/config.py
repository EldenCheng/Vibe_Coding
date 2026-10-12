"""配置加载：读取 config/devices.json，并提供路径常量。"""

import json
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "devices.json"


@dataclass
class Device:
    """一台电视盒子的连接信息。"""

    name: str
    host: str
    port: int
    note: str = ""

    @property
    def serial(self) -> str:
        """adb 用于寻址设备的 serial 字符串。"""
        return f"{self.host}:{self.port}"


@dataclass
class Settings:
    """整份配置。"""

    adb_path: str
    default_device: str
    screenshot_dir: Path
    connect_timeout: int
    devices: list

    def device_names(self) -> list:
        return [d.name for d in self.devices]

    def pick(self, name: str | None) -> Device:
        """按名称取设备；name 为空时用默认设备。"""
        target = name or self.default_device
        if not target:
            if len(self.devices) == 1:
                return self.devices[0]
            raise ConfigError(
                f"配置里没有 default_device，且存在多台设备：{self.device_names()}\n"
                f"请用 --device 指定其中一台。"
            )
        for d in self.devices:
            if d.name == target:
                return d
        raise ConfigError(
            f"未找到设备 {target!r}，可用设备：{self.device_names()}"
        )


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    """读取配置文件，缺失或格式错误时抛 ConfigError 并给出可执行的修复提示。"""
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}\n请先创建 config/devices.json。")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON：{path}\n{exc}") from exc

    devices = []
    for item in raw.get("devices", []):
        if not item.get("enabled", True):
            continue
        missing = [k for k in ("name", "host") if not item.get(k)]
        if missing:
            raise ConfigError(
                f"设备条目缺少字段 {missing}：{item}\n请补全 config/devices.json。"
            )
        devices.append(
            Device(
                name=item["name"],
                host=item["host"],
                port=int(item.get("port", 5555)),
                note=item.get("note", ""),
            )
        )

    if not devices:
        raise ConfigError(
            f"配置中没有任何可用设备：{path}\n请在 devices 里填入盒子的 name/host/port。"
        )

    out_dir = raw.get("screenshot_dir", "screen_shot")
    screenshot_dir = Path(out_dir)
    if not screenshot_dir.is_absolute():
        screenshot_dir = PROJECT_ROOT / screenshot_dir

    return Settings(
        adb_path=raw.get("adb_path") or "adb",
        default_device=raw.get("default_device") or "",
        screenshot_dir=screenshot_dir,
        connect_timeout=int(raw.get("connect_timeout", 10)),
        devices=devices,
    )
