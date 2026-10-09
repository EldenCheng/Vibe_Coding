# -*- coding: utf-8 -*-
"""配置装载：内置默认值 ← config.json ← CLI 覆盖，带类型校验与夹取。

与兄弟下载器一致：config.json 固定在**项目目录**（脚本自身目录）下，
相对路径按项目目录解析，与 cwd 无关。
"""
import copy
import json
from pathlib import Path

# 项目根目录（http-download/）
PROJECT_DIR = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "output_dir": "Download",
    "proxy": "",
    "headers": {},
    "concurrency": 4,
    "min_split_mb": 8,
    "speed_limit_kb": 0,
    "timeout": 30,
    "retry": {"max_attempts": 5, "backoff_base": 2.0, "backoff_multiplier": 2.0},
    "overwrite": "rename",
    "auto_verify": True,
}

OVERWRITE_CHOICES = ("rename", "overwrite", "skip")


class ConfigError(ValueError):
    """配置不合法（CLI / config.json）。会直接转成退出码 1 的错误输出。"""


def _deep_merge(base, override):
    """dict 递归合并，其余类型整体替换（与统一下载管理器同款语义）。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate(cfg):
    """夹取数值范围、校验枚举，就地修正后返回。"""
    cfg["concurrency"] = max(1, min(16, _to_int(cfg.get("concurrency"), 1)))
    cfg["min_split_mb"] = max(1, _to_int(cfg.get("min_split_mb"), 1))
    cfg["speed_limit_kb"] = max(0, _to_int(cfg.get("speed_limit_kb"), 0))
    cfg["timeout"] = max(3, _to_int(cfg.get("timeout"), 30))
    retry = cfg.get("retry") if isinstance(cfg.get("retry"), dict) else {}
    retry["max_attempts"] = max(1, _to_int(retry.get("max_attempts"), 1))
    retry["backoff_base"] = max(0.0, _to_float(retry.get("backoff_base"), 2.0))
    retry["backoff_multiplier"] = max(1.0, _to_float(retry.get("backoff_multiplier"), 2.0))
    cfg["retry"] = retry
    if cfg.get("overwrite") not in OVERWRITE_CHOICES:
        raise ConfigError(f"overwrite 取值不合法: {cfg.get('overwrite')!r}，"
                          f"应为 {'/'.join(OVERWRITE_CHOICES)}")
    if not isinstance(cfg.get("headers"), dict):
        raise ConfigError("headers 必须是对象（键值对）")
    cfg["auto_verify"] = bool(cfg.get("auto_verify"))
    return cfg


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_settings(config_path=None):
    """读取并校验配置，返回带 output_dir_abs 的设置字典。"""
    path = Path(config_path) if config_path else PROJECT_DIR / "config.json"
    data = copy.deepcopy(DEFAULTS)
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"读取 {path} 失败: {exc}") from exc
        if not isinstance(user, dict):
            raise ConfigError(f"{path} 的内容必须是 JSON 对象")
        data = _deep_merge(data, user)
    cfg = _validate(data)
    out = Path(str(cfg.get("output_dir") or "Download")).expanduser()
    cfg["output_dir_abs"] = str(out if out.is_absolute() else PROJECT_DIR / out)
    return cfg


def apply_cli(cfg, args):
    """把 argparse 命名空间里的覆盖项合并进 cfg（值为 None 表示未提供，不覆盖）。"""
    if getattr(args, "output_dir", None):
        p = Path(args.output_dir).expanduser()
        cfg["output_dir_abs"] = str(p if p.is_absolute() else PROJECT_DIR / p)
    if getattr(args, "proxy", None) is not None:
        cfg["proxy"] = str(args.proxy).strip()
    if getattr(args, "concurrency", None):
        cfg["concurrency"] = max(1, min(16, int(args.concurrency)))
    if getattr(args, "speed_limit", None) is not None:
        cfg["speed_limit_kb"] = max(0, int(args.speed_limit))
    if getattr(args, "overwrite", None):
        if args.overwrite not in OVERWRITE_CHOICES:
            raise ConfigError(f"overwrite 取值不合法: {args.overwrite!r}")
        cfg["overwrite"] = args.overwrite
    if getattr(args, "max_attempts", None):
        cfg["retry"]["max_attempts"] = max(1, int(args.max_attempts))
    for item in (getattr(args, "header", None) or []):
        if ":" not in item:
            raise ConfigError(f'--header 需要 "键: 值" 格式: {item!r}')
        key, value = item.split(":", 1)
        cfg["headers"][key.strip()] = value.strip()
