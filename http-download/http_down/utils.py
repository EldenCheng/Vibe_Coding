# -*- coding: utf-8 -*-
"""通用小工具：文件名解析与安全化、重名处理、哈希计算、人话字节数。"""
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Windows 文件名非法字符 + 控制符
_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME_LEN = 200


def human_size(num):
    """字节数 → "12.3 MB" 这类可读文本。"""
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return "-"


def sanitize_filename(name):
    """把任意字符串变成 Windows 安全的单级文件名（去非法字符、控制符、尾部点空格，限长）。"""
    name = _UNSAFE_RE.sub("_", str(name)).strip().rstrip(". ")
    if len(name) > MAX_NAME_LEN:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 20:
            name = stem[: MAX_NAME_LEN - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_NAME_LEN]
    return name or "download"


def filename_from_headers(headers):
    """从 Content-Disposition 解析文件名；RFC 5987 的 filename* 优先（支持中文）。"""
    cd = (headers or {}).get("Content-Disposition") or ""
    if not cd:
        return ""
    m = re.search(r"filename\*\s*=\s*([^']+)''([^;]+)", cd, re.I)
    if m:
        try:
            return unquote(m.group(2).strip(), m.group(1).strip() or "utf-8")
        except LookupError:
            return unquote(m.group(2).strip(), "utf-8")
    m = re.search(r'filename\s*=\s*"([^"]*)"', cd, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"filename\s*=\s*([^;]+)", cd, re.I)
    if m:
        return m.group(1).strip().strip('"')
    return ""


def filename_from_url(url):
    """取 URL 路径最后一段并解开百分号编码；失败返回空串。"""
    try:
        return unquote(urlsplit(url).path.rsplit("/", 1)[-1] or "")
    except ValueError:
        return ""


def unique_path(path: Path):
    """rename 策略：x.zip → x (2).zip → x (3).zip …返回第一个不存在的路径。"""
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    for k in range(2, 10000):
        cand = path.with_name(f"{stem} ({k}){ext}")
        if not cand.exists():
            return cand
    return path.with_name(f"{stem} ({int(time.time())}){ext}")


# 支持的哈希算法与十六进制长度（用于自动识别期望校验值）
HASH_ALGOS = {"sha256": 64, "md5": 32}
_HEX_RE = re.compile(r"[0-9a-f]+")


def detect_hash_algo(hex_str):
    """按长度识别校验值算法。返回 (algo, 归一化小写hex) 或 ("", "")。"""
    text = (hex_str or "").strip().lower()
    if _HEX_RE.fullmatch(text or ""):
        for algo, length in HASH_ALGOS.items():
            if len(text) == length:
                return algo, text
    return "", ""


def hash_file(path, algos=("sha256",)):
    """流式计算文件哈希，可一次算多种。返回 {algo: hexdigest}。"""
    ctxs = {a: hashlib.new(a) for a in algos}
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            for ctx in ctxs.values():
                ctx.update(blk)
    return {a: ctx.hexdigest() for a, ctx in ctxs.items()}


def parse_sha256_file(path):
    """解析 sha256sum 格式的校验文件（首列哈希，后面是可选文件名）。

    返回 (algo, hash)；解析不出就返回 ("", "")。
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return "", ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        algo, hexs = detect_hash_algo(line.split()[0])
        if algo:
            return algo, hexs
    return "", ""
