"""操作注册表：发现 automations/ 下的操作，校验编号与名称，维护编号台账。"""

import importlib
import json
import pkgutil
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = PROJECT_ROOT / "config" / "number_ledger.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_ATTRS = ("number", "name", "title", "run")

# 名称里不含 "-" 和 ","，否则会和选择器的区间/列表语法打架
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class RegistryError(RuntimeError):
    """操作定义不合法。"""


@dataclass(frozen=True)
class Operation:
    """一个自动化操作的元信息加执行入口。"""

    number: int
    name: str
    title: str
    description: str
    default_params: dict
    module: object

    @property
    def label(self) -> str:
        return f"{self.number} {self.name}"

    def __str__(self) -> str:
        return f"[{self.number}] {self.name} — {self.title}"


def _operation_from(module) -> Operation:
    """校验一个 automations 模块并转成 Operation。"""
    mod_name = _mod_of(module)

    missing = [a for a in REQUIRED_ATTRS if not hasattr(module, a)]
    if missing:
        raise RegistryError(f"automations/{mod_name}.py 缺少定义：{missing}")

    number = module.number
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise RegistryError(
            f"automations/{mod_name}.py 的 number 必须是正整数，当前是 {number!r}"
        )
    name = str(module.name).strip()
    if not NAME_RE.match(name):
        raise RegistryError(
            f"automations/{mod_name}.py 的 name={module.name!r} 不合法。\n"
            f"名称只能是小写字母开头、后接小写字母/数字/下划线（不含 - 和 ,，"
            f"否则会和选择器语法冲突）。"
        )
    if not callable(module.run):
        raise RegistryError(f"automations/{mod_name}.py 的 run 必须可调用")

    defaults = getattr(module, "default_params", {}) or {}
    if not isinstance(defaults, dict):
        raise RegistryError(f"automations/{mod_name}.py 的 default_params 必须是字典")
    bad_keys = [k for k in defaults if not isinstance(k, str) or k.startswith("_")]
    if bad_keys:
        raise RegistryError(
            f"automations/{mod_name}.py 的参数键名非法：{bad_keys}"
            f"（不能为空或以 _ 开头）"
        )

    return Operation(
        number=number,
        name=name,
        title=str(module.title),
        description=str(getattr(module, "description", "") or module.title),
        default_params=dict(defaults),
        module=module,
    )


def _load_module(mod_name: str) -> Operation:
    """导入 automations/<mod_name>.py 并校验。"""
    return _operation_from(importlib.import_module(f"automations.{mod_name}"))


def discover(on_new=None) -> list:
    """导入 automations 包下所有模块，返回按编号升序的操作列表。

    on_new: 可选回调，登记了新编号时以说明文本调用一次。
    """
    try:
        package = importlib.import_module("automations")
    except ImportError as exc:
        raise RegistryError(f"无法导入 automations 包：{exc}") from exc

    ops = []
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        ops.append(_load_module(info.name))

    _check_unique(ops)
    added = _sync_ledger(ops)
    if added and on_new:
        on_new(added)
    return sorted(ops, key=lambda o: o.number)


def _check_unique(ops: list) -> None:
    """编号与名称都必须唯一。"""
    for attr in ("number", "name"):
        seen = {}
        for op in ops:
            value = getattr(op, attr)
            if value in seen:
                raise RegistryError(
                    f"{attr}={value!r} 被两个操作同时使用："
                    f"automations/{seen[value]}.py 与 automations/{_mod_of(op.module)}.py"
                )
            seen[value] = _mod_of(op.module)


def _mod_of(module) -> str:
    return module.__name__.rsplit(".", 1)[-1]


def _load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return {}
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"编号台账损坏：{LEDGER_PATH}\n{exc}") from exc


def _sync_ledger(ops: list) -> list:
    """校验并登记编号，返回本次新增的登记说明。

    台账里出现过的编号永久属于当时那个操作名——下线操作不会释放编号，
    避免"昨天 3 号是截图、今天 3 号变成别的"。
    """
    ledger = _load_ledger()
    added = []

    for op in ops:
        key = str(op.number)
        owner = ledger.get(key)
        if owner is None:
            ledger[key] = op.name
            added.append(f"{key} → {op.name}")
        elif owner != op.name:
            raise RegistryError(
                f"编号 {op.number} 已登记给 {owner!r}，不能改派给 {op.name!r}。\n"
                f"编号一经使用永不复用——请给 {op.name} 换一个新编号。"
                f"（台账：{LEDGER_PATH}）"
            )

    if added:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        ordered = {k: ledger[k] for k in sorted(ledger, key=int)}
        LEDGER_PATH.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return added


def find(ops: list, key) -> Operation:
    """按编号或名称取操作，取不到抛 RegistryError。"""
    token = str(key).strip()

    if token.isdigit():
        number = int(token)
        for op in ops:
            if op.number == number:
                return op
        raise RegistryError(f"没有编号为 {number} 的操作。用 list 查看现有编号。")

    target = token.lower()
    for op in ops:
        if op.name.lower() == target:
            return op
    available = "、".join(f"{o.number}:{o.name}" for o in ops)
    raise RegistryError(f"没有名为 {key!r} 的操作。现有操作：{available}")
