"""m3u8 清单解析：master/media、AES-128 KEY、fMP4 init、DRM 检测。

纯手写解析（不依赖第三方 m3u8 库），只覆盖下载所需的最小子集：
EXTINF / EXT-X-KEY / EXT-X-SESSION-KEY / EXT-X-MAP / EXT-X-MEDIA-SEQUENCE /
EXT-X-STREAM-INF / EXT-X-BYTERANGE。
"""
from dataclasses import dataclass, field
from urllib.parse import urljoin

# Widevine / FairPlay 的 KEYFORMAT 标识，命中即为真 DRM
WIDEVINE_UUID = "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
DRM_KEYFORMATS = (WIDEVINE_UUID, "com.apple.streamingkeydelivery")


class DRMError(Exception):
    """检测到真正的 DRM 加密，无法在合规前提下处理。"""


@dataclass
class Key:
    method: str
    uri: str = None
    iv: bytes = None


@dataclass
class Segment:
    index: int
    url: str
    seq: int                    # 媒体序列号（IV 缺省时按规范用作 IV）
    key: Key = None
    init_url: str = None
    duration: float = 0.0       # #EXTINF 声明的切片时长（判定"要不要重下"用，v0.10.0）


@dataclass
class Variant:
    url: str
    bandwidth: int = 0
    resolution: str = ""
    codecs: str = ""


@dataclass
class Playlist:
    url: str                    # 重定向后的最终 URL（相对地址解析基准）
    raw: str
    is_master: bool = False
    segments: list = field(default_factory=list)
    variants: list = field(default_factory=list)
    media_sequence: int = 0
    init_url: str = None
    encrypted: bool = False
    has_byterange: bool = False
    # 从 master 跟进来时，记下**选中变体**声明的分辨率/带宽（v0.10.0）：
    # media 清单本身不带分辨率，判定"有没有更高清版本"要靠它
    variant_resolution: str = ""
    variant_bandwidth: int = 0

    @property
    def declared_duration(self):
        """清单声明的总时长（各切片 #EXTINF 之和，单位秒）。"""
        return sum(getattr(s, "duration", 0.0) or 0.0 for s in self.segments)


def _split_attrs(s):
    """按逗号切分属性串，引号内的逗号不切（小型状态机）。"""
    parts, buf, in_quote = [], "", False
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
            buf += ch
        elif ch == "," and not in_quote:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return parts


def _parse_attrs(s):
    """'METHOD=AES-128,URI="k.key",IV=0x1F' -> dict（键大写）"""
    out = {}
    for part in _split_attrs(s):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip().upper()] = v.strip().strip('"')
    return out


def _parse_iv(s):
    """IV 十六进制串转 16 字节（不足高位补零，规范为 128 位大端）。"""
    s = (s or "").strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    return bytes.fromhex(s).rjust(16, b"\x00")


def _check_drm(attrs):
    """命中 Widevine / FairPlay / SAMPLE-AES 时抛 DRMError（硬边界）。"""
    kf = attrs.get("KEYFORMAT", "")
    method = attrs.get("METHOD", "")
    if any(f in kf for f in DRM_KEYFORMATS):
        raise DRMError(f"检测到真 DRM 加密（KEYFORMAT={kf}）")
    if method.upper() == "SAMPLE-AES":
        raise DRMError("检测到 SAMPLE-AES 加密（常见于 FairPlay/Widevine 封装）")


def parse(text, base_url):
    """解析 m3u8 文本。base_url 必须是清单的真实 URL（重定向后）。"""
    pl = Playlist(url=base_url, raw=text)
    current_key = None
    current_init = None
    pending_stream_inf = None
    pending_duration = 0.0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-KEY") or line.startswith("#EXT-X-SESSION-KEY"):
            attrs = _parse_attrs(line.split(":", 1)[1])
            if attrs.get("METHOD", "NONE").upper() == "NONE":
                current_key = None
            else:
                _check_drm(attrs)
                current_key = Key(
                    method=attrs["METHOD"],
                    uri=urljoin(base_url, attrs["URI"]) if attrs.get("URI") else None,
                    iv=_parse_iv(attrs["IV"]) if attrs.get("IV") else None,
                )
        elif line.startswith("#EXT-X-MAP"):
            attrs = _parse_attrs(line.split(":", 1)[1])
            if attrs.get("URI"):
                current_init = urljoin(base_url, attrs["URI"])
        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            pl.media_sequence = int(line.split(":", 1)[1].strip() or 0)
        elif line.startswith("#EXT-X-STREAM-INF"):
            pending_stream_inf = _parse_attrs(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-BYTERANGE"):
            pl.has_byterange = True
        elif line.startswith("#EXTINF"):
            # 时长以前直接丢弃；v0.10.0 起留给 Segment：判定"要不要重下"要比对清单声明的总时长
            raw = line.split(":", 1)[1].split(",", 1)[0].strip()
            try:
                pending_duration = float(raw)
            except ValueError:
                pending_duration = 0.0
        elif line.startswith("#"):
            continue  # 其它标签/注释忽略
        else:
            # —— 非注释行：变体 URI 或切片 URI ——
            if pending_stream_inf is not None:
                pl.variants.append(Variant(
                    url=urljoin(base_url, line),
                    bandwidth=int(pending_stream_inf.get("BANDWIDTH", "0") or 0),
                    resolution=pending_stream_inf.get("RESOLUTION", ""),
                    codecs=pending_stream_inf.get("CODECS", ""),
                ))
                pending_stream_inf = None
            else:
                pl.segments.append(Segment(
                    index=len(pl.segments),
                    url=urljoin(base_url, line),
                    seq=pl.media_sequence + len(pl.segments),
                    key=current_key,
                    init_url=current_init,
                    duration=pending_duration,
                ))
                pending_duration = 0.0

    pl.is_master = bool(pl.variants) and not pl.segments
    pl.encrypted = any(s.key for s in pl.segments)
    pl.init_url = pl.segments[0].init_url if pl.segments else current_init
    if pl.has_byterange:
        print("[警告] 清单含 #EXT-X-BYTERANGE 切片，本版本暂不支持，结果可能不完整")
    return pl


def fetch_playlist(session, url):
    """拉取清单文本，返回 (文本, 重定向后的最终 URL)。"""
    resp = session.get(url, timeout=(15, 60))
    resp.raise_for_status()
    return resp.text, resp.url


def load_playlist(session, url, quality="best", variant_index=None, _depth=0, quiet=False):
    """高层入口：master 清单自动跟进变体，直到 media 清单。

    quiet=True 时不打印 "[清单] …"（下载前的自动判定只需要数据，不需要噪音日志）。
    返回的 media 清单上会带 `variant_resolution` / `variant_bandwidth`
    （选中变体声明的值），`declared_duration` 为该清单各切片 #EXTINF 之和。
    """
    if _depth > 5:
        raise RuntimeError("清单嵌套过深，中止（可能不是正常 HLS 站点）")
    text, final_url = fetch_playlist(session, url)
    pl = parse(text, final_url)
    if pl.is_master:
        if not pl.variants:
            raise RuntimeError("master 清单中未找到可用变体")
        if variant_index is not None:
            if not (0 <= variant_index < len(pl.variants)):
                raise RuntimeError(f"variant-index 超出范围（0~{len(pl.variants) - 1}）")
            v = pl.variants[variant_index]
        else:
            v = (max(pl.variants, key=lambda x: x.bandwidth) if quality == "best"
                 else min(pl.variants, key=lambda x: x.bandwidth))
        if not quiet:
            print(f"[清单] master 清单共 {len(pl.variants)} 个变体，"
                  f"选择 {v.resolution or '未知分辨率'} ({v.bandwidth // 1000} kbps)")
        media = load_playlist(session, v.url, quality, variant_index, _depth + 1, quiet)
        media.variant_resolution = v.resolution      # 把声明值带回去（v0.10.0）
        media.variant_bandwidth = v.bandwidth
        return media
    if not pl.segments:
        raise RuntimeError("media 清单中未解析到任何切片")
    if not quiet:
        print(f"[清单] 共 {len(pl.segments)} 个切片"
              + ("，AES-128 加密" if pl.encrypted else ""))
    return pl
