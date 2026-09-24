"""站点精修配置：sites/ 目录每站一个 JSON，按域名匹配加载。

未匹配到配置时返回 None，调用方回退通用引擎行为（v0.2.0 逻辑，不做精修）。
字段说明与示例见 sites/eacg.json 的 _说明 键；坏正则/坏字段自动忽略并告警，
保证一个写坏的站点文件不影响其他站点与整体流程。
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import config

SITES_DIR = config.PROJECT_ROOT / "sites"

_DEFAULT_FAILOVER = 3   # 单集默认最多尝试的主+备选线路总数


@dataclass
class SiteConfig:
    name: str = ""
    domains: list = field(default_factory=list)
    play_pattern: object = None      # 编译后的正则或 None
    group: dict = field(default_factory=dict)   # {"id":1,"line":2,"ep":3}
    line_preference: str = "line_asc"           # line_asc | complete_first
    label_strip: str = ""            # 集名尾部噪声正则
    title_subs: list = field(default_factory=list)  # [[正则, 替换], ...]
    desc_prefix: str = ""            # 简介前噪声正则
    desc_suffix: str = ""            # 简介后噪声正则
    failover_max: int = _DEFAULT_FAILOVER

    # ---------- 精修清洗 ----------
    def clean_label(self, text):
        """集名清洗：剥掉 label_strip 正则命中的尾部噪声（如'第12集完结'）。"""
        if self.label_strip and text:
            try:
                return re.sub(self.label_strip, "", text).strip()
            except re.error:
                pass
        return (text or "").strip()

    def clean_title(self, title):
        """单集成品命名：按 title_subs 逐条替换，剥掉页面标题噪声。"""
        for pat, repl in self.title_subs:
            try:
                title = re.sub(pat, repl, title or "")
            except re.error:
                continue
        return re.sub(r"\s+", " ", (title or "").strip()).strip(" -_")

    def clean_desc(self, desc):
        """简介清洗：剥掉配置的前/后噪声正则。"""
        for pat in (self.desc_prefix, self.desc_suffix):
            if pat and desc:
                try:
                    desc = re.sub(pat, "", desc, count=1).strip()
                except re.error:
                    continue
        return desc.strip()

    def extract_parts(self, url):
        """按 play_pattern 解析播放页 URL → (id, line_no, ep_pos)；不匹配返回 None。"""
        if self.play_pattern is None:
            return None
        m = self.play_pattern.search(urlparse(url).path)
        if not m:
            return None
        g = self.group or {}
        try:
            vid = m.group(g.get("id", 1))
            line = int(m.group(g.get("line", 2)))
            ep = str(m.group(g.get("ep", 3)))
        except (IndexError, ValueError):
            return None
        return vid, line, ep


def parse(raw, source=""):
    """原始 dict → SiteConfig（坏字段容错忽略）。"""
    cfg = SiteConfig(name=str(raw.get("name") or Path(source).stem))
    cfg.domains = [str(d).lower().lstrip(".") for d in raw.get("domains") or []]
    pat = raw.get("play_pattern")
    if pat:
        try:
            cfg.play_pattern = re.compile(str(pat))
        except re.error as e:
            print(f"[站点] {cfg.name} play_pattern 无效已忽略: {e}")
    g = raw.get("group")
    if isinstance(g, dict):
        cfg.group = {k: int(v) for k, v in g.items() if str(v).isdigit()}
    pref = str(raw.get("line_preference") or "").strip()
    if pref in ("line_asc", "complete_first"):
        cfg.line_preference = pref
    cfg.label_strip = str(raw.get("label_strip") or "")
    subs = raw.get("title_subs")
    if isinstance(subs, list):
        cfg.title_subs = [(str(p), str(r)) for p, r in
                          (s if isinstance(s, (list, tuple)) else (s, "") for s in subs)]
    cfg.desc_prefix = str(raw.get("desc_prefix") or "")
    cfg.desc_suffix = str(raw.get("desc_suffix") or "")
    try:
        cfg.failover_max = max(1, int(raw.get("failover_max", _DEFAULT_FAILOVER)))
    except (TypeError, ValueError):
        cfg.failover_max = _DEFAULT_FAILOVER
    return cfg


def load_all(sites_dir=None):
    """加载 sites/ 下全部 *.json → [SiteConfig]；目录不存在返回空表。"""
    d = Path(sites_dir) if sites_dir else SITES_DIR
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            out.append(parse(json.loads(f.read_text(encoding="utf-8")), str(f)))
        except Exception as e:
            print(f"[站点] {f.name} 加载失败已跳过: {e}")
    return out


def match(url, sites_dir=None):
    """按域名后缀匹配播放页/列表页 URL → SiteConfig 或 None。"""
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    if not host:
        return None
    for cfg in load_all(sites_dir):
        for dom in cfg.domains:
            if host == dom or host.endswith("." + dom):
                return cfg
    return None
