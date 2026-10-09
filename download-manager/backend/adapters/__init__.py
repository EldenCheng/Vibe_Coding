"""适配器注册表。"""
from .e_download import EDownloadAdapter
from .fetch_xs import FetchXsAdapter
from .http_download import HttpDownloadAdapter
from .m3u_down import M3uDownAdapter

ADAPTER_CLASSES = (FetchXsAdapter, EDownloadAdapter, M3uDownAdapter, HttpDownloadAdapter)


def build_adapters(cfg):
    """按当前配置实例化所有适配器，返回 {type_id: adapter}。"""
    return {cls.type_id: cls(cfg) for cls in ADAPTER_CLASSES}


def rebuild(cfg):
    return build_adapters(cfg)
