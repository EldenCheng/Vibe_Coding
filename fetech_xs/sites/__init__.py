"""站点注册表：按 URL / book_id 分发到对应站点适配器。

分发规则：
- 纯数字参数 → 爱丽丝书屋 book_id（向后兼容）
- 含 URL → 按域名匹配；无匹配时回落爱丽丝书屋
"""
from .base import SiteAdapter
from .alice_book import AliceBookAdapter
from .cool18 import Cool18Adapter

# 注册顺序即匹配优先级（先注册先匹配）
_ADAPTERS = [
    AliceBookAdapter,
    Cool18Adapter,
]


def get_adapter(entry, config=None):
    """返回一个适配器实例。entry 为 book_id 或入口 URL。"""
    text = str(entry).strip()
    if text.isdigit():
        return AliceBookAdapter(config or {})
    for cls in _ADAPTERS:
        if cls.matches(text):
            return cls(config or {})
    return AliceBookAdapter(config or {})


__all__ = ["SiteAdapter", "get_adapter"]
