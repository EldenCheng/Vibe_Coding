"""切片并发下载 + progress.json 断点续传 + AES-128 解密 + 自动合并。"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from Crypto.Cipher import AES

from . import config, merger
from .utils import ext_from_url, render_progress, sanitize_name


def _unpad(data):
    """PKCS7 去填充；非标准填充时容错返回原文（部分切片台不规范）。"""
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data


def _decrypt(data, key, iv):
    """AES-128-CBC 解密 + 去填充。"""
    return _unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data))


def default_out_dir(playlist_url, base=None):
    """根据清单 URL 推断默认输出目录：downloads/<可读标题>/。"""
    parsed = urlparse(playlist_url)
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    stem = tail.rsplit(".", 1)[0] if "." in tail else tail
    # index/playlist 之类泛化名没有区分度，改用域名
    if stem.lower() in ("", "index", "playlist", "master", "video", "hls"):
        stem = parsed.netloc.replace(":", "_")
    return Path(base or config.OUTPUT_DIR) / sanitize_name(stem)


class _Progress:
    """progress.json 读写（线程安全），重跑同一命令即可续传。"""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data = {"playlist_url": "", "total": 0, "finished": False, "segments": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass  # 进度文件损坏则从头开始

    def _flush(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def set_meta(self, playlist_url, total):
        with self.lock:
            self.data["playlist_url"] = playlist_url
            self.data["total"] = total
            self._flush()

    def done_map(self, seg_dir):
        """已完成切片 {序号: 文件名}；校验文件存在且大小与记录一致（防截断片）。"""
        out = {}
        for k, v in self.data.get("segments", {}).items():
            if not (v.get("done") and v.get("size", 0) > 0):
                continue
            f = seg_dir / v["file"]
            try:
                if not f.exists() or f.stat().st_size != int(v["size"]):
                    continue   # 缺失或大小不符：视为未完成，续传时自动重下
            except OSError:
                continue
            out[int(k)] = v["file"]
        return out

    def mark(self, index, filename, size):
        with self.lock:
            self.data.setdefault("segments", {})[str(index)] = {
                "file": filename, "done": True, "size": size}
            self._flush()


def _fetch_keys(session, playlist):
    """下载清单里出现的全部 KEY（16 字节），返回 {key_uri: bytes}。"""
    keys = {}
    for seg in playlist.segments:
        k = seg.key
        if k is None or not k.uri or k.uri in keys:
            continue
        resp = session.get(k.uri, timeout=config.TIMEOUT)
        resp.raise_for_status()
        if len(resp.content) != 16:
            raise RuntimeError(f"KEY 长度异常（{len(resp.content)} 字节，应为 16）: {k.uri}")
        keys[k.uri] = resp.content
    return keys


def _download_one(session, seg, key_bytes, seg_dir):
    """下载（按需解密）单个切片，返回 (index, 文件名, 字节数)，失败退避重试。"""
    last_err = None
    for attempt in range(1, config.RETRY_TIMES + 1):
        try:
            resp = session.get(seg.url, timeout=config.TIMEOUT)
            resp.raise_for_status()
            data = resp.content
            # 完整性校验：服务端声明长度与实际不符（静默截断）按失败重试
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit() and len(data) != int(cl):
                raise ValueError(f"响应不完整（{len(data)}/{cl} 字节）")
            if seg.key is not None and key_bytes:
                # IV 缺省时按 HLS 规范使用媒体序列号（16 字节大端）
                iv = seg.key.iv or seg.seq.to_bytes(16, "big")
                data = _decrypt(data, key_bytes, iv)
            fname = f"{seg.index:06d}{ext_from_url(seg.url)}"
            (seg_dir / fname).write_bytes(data)
            return seg.index, fname, len(data)
        except Exception as e:  # 网络错误 / 解密异常都重试
            last_err = e
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise RuntimeError(f"切片 #{seg.index} 下载失败: {last_err}")


def _ensure_init(session, playlist, seg_dir):
    """fMP4 场景：确保 init 段已下载，返回文件名（无 init 返回 None）。"""
    if not playlist.init_url:
        return None
    fname = "init" + ext_from_url(playlist.init_url, ".mp4")
    p = seg_dir / fname
    if not p.exists() or p.stat().st_size == 0:
        resp = session.get(playlist.init_url, timeout=config.TIMEOUT)
        resp.raise_for_status()
        p.write_bytes(resp.content)
    return fname


def finalize(out_dir, seg_files, init_fname=None, output_name="output.mp4"):
    """全部切片就绪后：写 concat 列表 → ffmpeg 合并 → 完整性自检 → 报告产物。"""
    print("\n[合并] 调用 ffmpeg 合并切片 ...")
    out_dir = Path(out_dir)
    out = merger.merge(out_dir, out_dir / "segments", seg_files,
                       output_name=output_name, init_fname=init_fname)
    try:
        merger.check_output(out)
    except Exception:
        out.unlink(missing_ok=True)   # 删掉坏成品，保留切片现场供重跑
        raise
    print(f"[完成] {out}  ({out.stat().st_size / 1048576:.1f} MB)")
    return out


def run(session, playlist, out_dir=None, concurrency=None, output_name="output.mp4"):
    """下载全部切片并合并，返回成品路径。中断后重跑同一命令可续传。"""
    out_dir = Path(out_dir) if out_dir else default_out_dir(playlist.url)
    seg_dir = out_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "playlist.m3u8").write_text(playlist.raw, encoding="utf-8")

    prog = _Progress(out_dir / "progress.json")
    prog.set_meta(playlist.url, len(playlist.segments))
    ok = prog.done_map(seg_dir)

    todo = [s for s in playlist.segments if s.index not in ok]
    print(f"[下载] 输出目录: {out_dir}")
    if ok:
        print(f"[下载] 续传：已完成 {len(ok)} 个，待下载 {len(todo)} 个")
    if not todo:
        return _finish(session, playlist, out_dir, seg_dir, ok, output_name)

    keys = _fetch_keys(session, playlist)
    failures = []
    total = len(playlist.segments)
    with ThreadPoolExecutor(max_workers=concurrency or config.CONCURRENCY) as pool:
        futures = {pool.submit(_download_one, session, s,
                               keys.get(s.key.uri) if s.key else None, seg_dir): s
                   for s in todo}
        # 字节统计含续传部分，进度条据此计算速度/ETA
        bytes_done = sum(int(v.get("size", 0))
                         for k, v in prog.data.get("segments", {}).items()
                         if int(k) in ok)
        t0 = time.time()
        try:
            for fut in as_completed(futures):
                try:
                    idx, fname, size = fut.result()
                    ok[idx] = fname
                    prog.mark(idx, fname, size)
                    bytes_done += size
                    bar = render_progress(len(ok), total, bytes_done, time.time() - t0)
                    print(f"\r[下载] {bar}", end="", flush=True)
                except Exception as e:
                    failures.append(str(e))
        except KeyboardInterrupt:
            print("\n[下载] 用户中断，进度已保存，重跑同一命令可续传")
            raise

    print()
    if failures:
        raise RuntimeError(
            f"{len(failures)} 个切片最终失败（前 5 条）：\n" + "\n".join(failures[:5])
            + "\n重跑同一命令即可续传未完成的切片")
    return _finish(session, playlist, out_dir, seg_dir, ok, output_name)


def _finish(session, playlist, out_dir, seg_dir, seg_files, output_name):
    """下载完成后补齐 init 段并合并。"""
    init_fname = _ensure_init(session, playlist, seg_dir)
    return finalize(out_dir, seg_files, init_fname=init_fname, output_name=output_name)
