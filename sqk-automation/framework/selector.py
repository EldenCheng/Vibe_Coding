"""选择器解析：把 "1" / "screenshot" / "1-10" / "[1, 3, 5]" 变成操作列表。"""

import re

from . import registry

RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


class SelectorError(RuntimeError):
    """选择器写法无法解析。"""


def parse(specs: list, ops: list) -> list:
    """解析命令行给出的若干选择器，返回待执行的操作序列（允许重复）。

    - 单个选择器内部可以用逗号分隔，外层方括号可选："[1, 3]" 与 "1,3" 等价
    - 多个选择器之间用空格分隔：run 1 3 5
    """
    selected = []
    for spec in specs:
        selected.extend(_parse_one(spec, ops))
    if not selected:
        raise SelectorError("没有解析到任何操作。")
    return selected


def _parse_one(spec: str, ops: list) -> list:
    text = spec.strip()
    if not text:
        raise SelectorError("选择器不能是空字符串。")

    if text.lower() == "all":
        return list(ops)

    opens, closes = text.startswith("["), text.endswith("]")
    if opens != closes:
        raise SelectorError(f"选择器 {spec!r} 的方括号不成对。")
    if opens:
        text = text[1:-1].strip()

    if "," in text:
        items = [t.strip() for t in text.split(",")]
        if not all(items):
            raise SelectorError(f"选择器 {spec!r} 里有空项。")
        out = []
        for item in items:
            out.extend(_parse_item(item, ops, spec))
        return out

    return _parse_item(text, ops, spec)


def _parse_item(token: str, ops: list, origin: str) -> list:
    """解析一个选择器项：编号 / 名称 / 编号区间。"""
    match = RANGE_RE.match(token)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            raise SelectorError(f"区间 {token!r} 起点大于终点。")
        # 区间取宽松语义：落在范围内、当前存在的操作，按编号升序
        picked = [o for o in ops if low <= o.number <= high]
        if not picked:
            existing = "、".join(str(o.number) for o in ops)
            raise SelectorError(
                f"区间 {token!r} 里没有任何操作。当前存在的编号：{existing}"
            )
        return picked

    if token.lower() == "all":
        raise SelectorError(f"all 只能整体使用，不能出现在列表里：{origin!r}")

    return [registry.find(ops, token)]
