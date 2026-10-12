"""Context：传给每个操作的运行上下文，屏蔽"设备从哪来、参数是什么"的细节。"""

import json
from pathlib import Path

from adb_kit import adb
from adb_kit.config import CONFIG_PATH, Settings

PARAMS_PATH = CONFIG_PATH.parent / "params.json"


class ParamsError(RuntimeError):
    """参数文件损坏或格式不对。"""


def load_params(path: Path = PARAMS_PATH) -> dict:
    """读取 config/params.json；文件不存在时返回空字典（全部走默认值）。"""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ParamsError(f"参数文件不是合法 JSON：{path}\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ParamsError(f"参数文件顶层必须是对象：{path}")
    return raw


class Context:
    """一次操作中脚本可用的环境：设备、参数、输出目录、日志。"""

    def __init__(self, settings: Settings, device, op, merged: dict, declared: dict):
        self.settings = settings
        self.device = device
        self.op = op
        self._params = merged
        self._declared = declared

    @classmethod
    def build(cls, op, settings: Settings, params_file: dict, warn_unknown: bool = True) -> "Context":
        """取 params.json 里属于本操作的那一段，叠加到 default_params 上。"""
        section = params_file.get(op.name, {})
        if not isinstance(section, dict):
            raise ParamsError(
                f"params.json 里 {op.name!r} 这一段必须是对象，"
                f"当前是 {type(section).__name__}"
            )

        merged = dict(op.default_params)
        merged.update(section)

        ctx = cls(settings, None, op, merged, section)
        if warn_unknown:
            unknown = [k for k in section if k not in op.default_params]
            if unknown:
                ctx.warn(
                    f"params.json 的 {op.name} 段有未知参数 {unknown}，已忽略。"
                    f"可用参数：{sorted(op.default_params) or '无'}"
                )
        return ctx

    # ---- 参数 ----

    def param(self, key):
        """取本操作的参数；未声明的键直接报错，避免静默拿到 None。"""
        if key not in self._params:
            raise KeyError(f"操作 {self.op.name} 没有声明参数 {key!r}")
        return self._params[key]

    @property
    def params(self) -> dict:
        return dict(self._params)

    # ---- 设备 ----

    def attach_device(self, device) -> None:
        self.device = device

    def ensure_connected(self) -> None:
        """连接设备并等待其可执行命令；对已连接的设备重复调用是安全的。"""
        settings, device = self.settings, self.device
        self.log(f"目标设备：{device.name} ({device.serial})")
        self.log(f"连接 → {adb.connect(settings, device)}")
        if not adb.wait_online(settings, device, seconds=settings.connect_timeout):
            raise adb.AdbError(f"{device.serial} 未进入可命令状态。")

    # ---- 日志 ----

    def log(self, message: str) -> None:
        print(f"  {message}")

    def warn(self, message: str) -> None:
        print(f"  [注意] {message}")
