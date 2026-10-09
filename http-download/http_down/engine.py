# -*- coding: utf-8 -*-
"""下载引擎：探测 → 单流/分块 → 限速/重试 → 组装 → 校验 → 落盘。

线程模型：
- 分块模式用 ThreadPoolExecutor 跑 N 个 worker，每段一个独立连接 + 独立 `.part.seg<i>` 文件；
- 主线程轮询 futures，每 2 秒把聚合字节数落盘到 progress.json，每 5 秒打印一次速度；
- 所有 worker 共享一个 TokenBucket（限速是总口径）与一个 Counter。
"""
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import progress as prog
from . import utils

CHUNK = 1024 * 1024          # 每次 iter_content 读写的块大小
PROGRESS_INTERVAL = 2.0      # 进度落盘间隔（秒）
PRINT_INTERVAL = 5.0         # 进度打印间隔（秒）
BACKOFF_CAP = 60.0           # 单次退避上限（秒）
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class FatalError(RuntimeError):
    """不可重试的错误（4xx、校验值非法等）。"""


class RetryExhausted(FatalError):
    """重试次数耗尽。"""


class RangeUnsupported(FatalError):
    """服务器不支持 Range 分块，需要回退单流。"""


class RetryableHTTP(FatalError):
    """可重试的 HTTP 状态码（429/5xx）。"""

    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class TokenBucket:
    """线程安全令牌桶：多 worker 共享一个总口径限速；rate<=0 表示不限速。"""

    def __init__(self, bytes_per_sec):
        self.rate = max(0.0, float(bytes_per_sec))
        self._tokens = 0.0
        self._ts = time.monotonic()
        self._lock = threading.Lock()

    def take(self, n):
        """取 n 字节令牌；不足则睡一小会儿再来（限速的粒度就是这里）。"""
        if self.rate <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                # 桶容量设为 2 秒的量，兼顾突发与平滑
                self._tokens = min(self.rate * 2, self._tokens + (now - self._ts) * self.rate)
                self._ts = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                need = n - self._tokens
            time.sleep(min(max(need / self.rate, 0.02), 0.5))


class Counter:
    """线程安全的字节计数器（只统计本次运行新写入的字节）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._value = 0

    def add(self, n):
        with self._lock:
            self._value += n

    def reset(self):
        with self._lock:
            self._value = 0

    def get(self):
        with self._lock:
            return self._value


class DownloadJob:
    """单个 URL 的下载任务（一个进程跑一个 Job，天然避开并发写冲突）。"""

    def __init__(self, url, cfg, filename="", expected_hash="", expected_algo="", print_fn=print):
        self.url = url
        self.s = cfg
        self.filename = (filename or "").strip()
        self.expected_hash = (expected_hash or "").lower()
        self.hash_algo = expected_algo
        self._print = print_fn

        self.output_dir = Path(cfg["output_dir_abs"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 运行期状态
        self.final_path = None        # 最终文件路径
        self.part_path = None         # <名>.part
        self.bytes_total = None       # None = 服务器没给 Content-Length
        self.accept_ranges = False
        self.final_url = url
        self.mode = "single"
        self.segments = []            # [(idx, start, end)]，分块模式使用
        self.resume_base = 0          # 本次启动前已存在的字节数
        self.bytes_done = 0           # resume_base + counter
        self.actual_sha256 = ""
        self.skipped = False
        self.progress_file = None

        self.counter = Counter()
        self.bucket = TokenBucket(cfg["speed_limit_kb"] * 1024)
        self._last_save = 0.0
        self._last_print = 0.0
        self._speed_mark_t = time.monotonic()
        self._speed_mark_b = 0

        self.session = self._make_session()

    # -------------------------------------------------------------- 会话

    def _make_session(self):
        """装配 requests 会话：默认头 + 用户头 + 代理语义（留空=读系统代理）。"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": UA,
            # 明确不要压缩传输：否则 Content-Length 与落盘字节数对不上
            "Accept-Encoding": "identity",
        })
        session.headers.update(self.s.get("headers") or {})
        proxy = (self.s.get("proxy") or "").strip()
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
        # proxy 留空时不关 trust_env：requests 会读环境变量与操作系统代理设置
        return session

    # -------------------------------------------------------------- 对外入口

    def run(self):
        """执行下载，返回结果字典（status/path/...），绝不抛异常。"""
        result = {"status": "failed", "path": "", "file": "", "bytes_total": 0,
                  "actual_sha256": "", "error": "", "note": ""}
        try:
            self._run_inner(result)
        except KeyboardInterrupt:
            # 进度已随 saves 落盘；重新抛出让入口层立刻退出（worker 线程随进程结束）
            self._print("已中断，进度已保留，下次运行同一命令会自动续传")
            raise
        except Exception as exc:  # noqa: BLE001  引擎兜底：任何异常都转成失败结果
            result["error"] = str(exc)
            self._print(f"下载失败: {exc}")
        if not self.skipped:
            self.bytes_done = self.resume_base + self.counter.get()
        self._save_progress(result=result)
        return result

    def _run_inner(self, result):
        t0 = time.monotonic()
        self._probe()

        # 定文件名 + 重名/跳过策略（可能改 final_path）
        if not self._decide_name_and_policy(result):
            return

        self.progress_file = prog.progress_path(self.output_dir, self.final_path.name, self.url)
        self._print(f"进度文件: {self.progress_file}")

        old = prog.read(self.progress_file) or {}
        self._decide_mode(old)

        size_text = utils.human_size(self.bytes_total) if self.bytes_total else "未知"
        self._print(f"文件大小: {size_text}")
        self._print(f"断点续传: {'是' if self.resume_base else '否'}，已有 {utils.human_size(self.resume_base)}")
        self._print(f"分块数: {len(self.segments) if self.mode == 'multi' else 1}")

        # 分块模式：段边界与上次不一致时，旧段文件全部作废（防错位拼接）
        if self.mode == "multi" and old.get("segments") != [list(x) for x in self.segments]:
            self._cleanup_segments()

        try:
            if self.mode == "multi":
                self._run_multi()
            else:
                self._run_single()
            self._assemble()
            if self._verify_and_promote(result):
                result["status"] = "complete"
                cost = time.monotonic() - t0
                avg = self.bytes_done / cost / 1024 / 1024 if cost > 0 else 0
                self._print(f"完成: {self.final_path.name} 共 {utils.human_size(self.bytes_done)}"
                            f"，平均 {avg:.1f} MB/s")
        except RangeUnsupported:
            # 只有分块阶段才会出这个错：回退单流重下
            self._print("服务器不支持 Range 分块，回退单流下载")
            self._cleanup_segments()
            self.counter.reset()
            self.resume_base = 0
            self.mode = "single"
            self.segments = []
            self._run_single()
            self._assemble()
            if self._verify_and_promote(result):
                result["status"] = "complete"

        result["path"] = str(self.final_path)
        result["file"] = self.final_path.name
        result["bytes_total"] = self.bytes_total or self.bytes_done
        result["actual_sha256"] = self.actual_sha256

    # -------------------------------------------------------------- 探测与策略

    def _probe(self):
        """不带 Range 的 GET：拿最终 URL、Content-Length、Accept-Ranges、Content-Disposition。"""
        timeout = self.s["timeout"]
        resp = self.session.get(self.url, stream=True, timeout=(timeout, timeout))
        with resp:
            if resp.status_code >= 400:
                raise FatalError(f"HTTP {resp.status_code}（探测阶段）")
            self.final_url = resp.url
            self.bytes_total = int(resp.headers.get("Content-Length") or 0) or None
            self.accept_ranges = "bytes" in (resp.headers.get("Accept-Ranges") or "").lower()
            cd_name = utils.filename_from_headers(resp.headers)

        # 文件名优先级：CLI > Content-Disposition > URL basename > 时间戳兜底
        raw = self.filename or cd_name or utils.filename_from_url(self.final_url)
        if raw:
            name = utils.sanitize_filename(raw)
        else:
            name = f"download_{time.strftime('%Y%m%d_%H%M%S')}.bin"
        self._print(f"保存文件名: {name}")
        self.final_path = self.output_dir / name

    def _decide_name_and_policy(self, result):
        """处理重名策略与 .part 续传判定。返回 False 表示已跳过（无需下载）。"""
        part = self.final_path.with_name(self.final_path.name + ".part")
        have = part.stat().st_size if part.exists() else 0

        if self.final_path.exists() and have == 0:
            policy = self.s["overwrite"]
            if policy == "skip":
                self._print(f"文件已存在，跳过: {self.final_path}")
                self.skipped = True
                result["status"] = "complete"
                result["note"] = "文件已存在，跳过"
                result["path"] = str(self.final_path)
                result["file"] = self.final_path.name
                result["bytes_total"] = self.final_path.stat().st_size
                self.bytes_done = result["bytes_total"]
                return False
            if policy == "rename":
                new = utils.unique_path(self.final_path)
                self._print(f"已改名为: {new.name}")
                self.final_path = new
        # overwrite 策略：什么都不做，最后 os.replace 自然覆盖
        self.part_path = self.final_path.with_name(self.final_path.name + ".part")
        return True

    def _decide_mode(self, old_progress):
        """决定单流还是分块，并算出续传起点。"""
        have_part = self.part_path.stat().st_size if self.part_path.exists() else 0
        want_multi = (self.s["concurrency"] > 1
                      and self.bytes_total is not None
                      and self.bytes_total >= self.s["min_split_mb"] * 1024 * 1024
                      and self.accept_ranges)
        if want_multi:
            self.mode = "multi"
            self.segments = self._plan_segments()
            # 段边界与上次一致才允许续传段文件（错位拼接比重下更糟）
            if old_progress.get("segments") == [list(x) for x in self.segments]:
                self.resume_base = sum(self._seg_have(i) for (i, _s, _e) in self.segments)
            else:
                self.resume_base = 0
        else:
            self.mode = "single"
            self.segments = []
            # 上次是分块跑到一半：段文件与 .part 不是一套账，只能从零单流
            self.resume_base = have_part if old_progress.get("mode") != "multi" else 0
            if have_part and self.resume_base == 0:
                self._print("上次为分块下载且段边界已失效，.part 不适用，本次单流重下")

    def _plan_segments(self):
        """把 [0, total) 均分为 concurrency 段；段边界只由 (total, 段数) 决定，保证可复现。"""
        total, n = self.bytes_total, min(self.s["concurrency"], self.bytes_total)
        base = total // n
        segs, start = [], 0
        for i in range(n):
            end = total - 1 if i == n - 1 else start + base - 1
            if end >= start:
                segs.append((i, start, end))
            start = end + 1
        return segs

    def _seg_path(self, idx):
        return self.part_path.with_name(f"{self.part_path.name}.seg{idx}")

    def _seg_have(self, idx):
        try:
            return self._seg_path(idx).stat().st_size
        except OSError:
            return 0

    def _cleanup_segments(self):
        for (i, _s, _e) in self.segments:
            try:
                self._seg_path(i).unlink()
            except OSError:
                pass

    # -------------------------------------------------------------- 下载

    def _backoff(self, attempt):
        delay = self.s["retry"]["backoff_base"] * (self.s["retry"]["backoff_multiplier"] ** (attempt - 1))
        time.sleep(min(delay, BACKOFF_CAP))

    @staticmethod
    def _raise_http(code):
        """把状态码翻译成可重试 / 不可重试异常。"""
        if code == 429 or 500 <= code < 600:
            raise RetryableHTTP(code)
        raise FatalError(f"HTTP {code}")

    def _tick(self):
        """主线程节拍器：节流落盘 + 节流打印速度。"""
        self.bytes_done = self.resume_base + self.counter.get()
        now = time.monotonic()
        if now - self._last_save >= PROGRESS_INTERVAL:
            self._save_progress()
            self._last_save = now
        if now - self._last_print >= PRINT_INTERVAL:
            dt = now - self._speed_mark_t
            if dt > 0:
                speed = (self.bytes_done - self._speed_mark_b) / dt / 1024 / 1024
                self._print(f"下载中: {utils.human_size(self.bytes_done)}"
                            f" / {utils.human_size(self.bytes_total) if self.bytes_total else '?'}"
                            f" ({speed:.1f} MB/s)")
            self._last_print = now
            self._speed_mark_t = now
            self._speed_mark_b = self.bytes_done

    def _run_single(self):
        """单流下载：一个连接从头/断点拉到尾；连接断了就带 Range 重来。"""
        # 续传起点已在 _decide_mode 里算好（上次为分块残留时会被清零）
        pos = self.resume_base
        max_att = self.s["retry"]["max_attempts"]
        attempt = 0
        while True:
            if self.bytes_total is not None and pos >= self.bytes_total:
                break
            attempt += 1
            if attempt > max_att:
                raise RetryExhausted(f"重试 {max_att} 次仍未完成")
            try:
                headers = {"Range": f"bytes={pos}-"} if pos > 0 else {}
                resp = self.session.get(self.url, headers=headers, stream=True,
                                        timeout=(self.s["timeout"], self.s["timeout"]))
                if resp.status_code == 416:
                    resp.close()
                    pos = self._handle_416(pos)
                    if pos is None:
                        break          # .part 其实已经完整
                    attempt = 0
                    continue
                if resp.status_code == 200 and pos > 0:
                    # 服务器无视了 Range：只能从头来
                    pos = 0
                    self.counter.reset()
                    self.resume_base = 0
                if resp.status_code not in (200, 206):
                    resp.close()
                    self._raise_http(resp.status_code)
                if self.bytes_total is None and resp.headers.get("Content-Length"):
                    self.bytes_total = pos + int(resp.headers["Content-Length"])
                append = (resp.status_code == 206 and pos > 0)
                if not append:
                    pos = 0
                # 换了新连接，速度窗口从头统计，避免第一口速度虚高
                self._last_print = time.monotonic()
                self._speed_mark_t = time.monotonic()
                self._speed_mark_b = self.bytes_done
                with open(self.part_path, "ab" if append else "wb") as fh:
                    for chunk in resp.iter_content(CHUNK):
                        if not chunk:
                            continue
                        self.bucket.take(len(chunk))
                        fh.write(chunk)
                        pos += len(chunk)
                        self.counter.add(len(chunk))
                        self._tick()
                resp.close()
                if self.bytes_total is None:
                    self.bytes_total = pos     # 流自然结束
                    break
                # 走到这说明流提前断了，循环回去带 Range 续
            except (requests.RequestException, OSError, RetryableHTTP) as exc:
                self._print(f"网络异常（第 {attempt}/{max_att} 次尝试），退避后重试: {exc}")
                self._backoff(attempt)

    def _handle_416(self, pos):
        """416 = 服务器认为范围非法。核对真实大小：一致则视为已完成，否则 .part 作废重下。

        返回 None 表示已完成（调用方直接跳出）；否则返回新的续传位置。
        """
        timeout = self.s["timeout"]
        resp = self.session.get(self.url, stream=True, timeout=(timeout, timeout))
        with resp:
            if resp.status_code >= 400:
                raise FatalError(f"HTTP {resp.status_code}（核对文件大小时）")
            total = int(resp.headers.get("Content-Length") or 0) or None
        if total is not None and pos == total:
            self.bytes_total = total
            return None
        self._print("服务器上的文件与本地 .part 不一致，丢弃 .part 重新下载")
        self.part_path.unlink(missing_ok=True)
        self.counter.reset()
        self.resume_base = 0
        self.bytes_total = total
        return 0

    def _run_multi(self):
        """分块下载：N 个 worker 各拉各的段，主线程轮询落进度。"""
        max_att = self.s["retry"]["max_attempts"]
        try:
            with ThreadPoolExecutor(max_workers=len(self.segments)) as pool:
                futs = [pool.submit(self._download_segment, i, s, e, max_att)
                        for (i, s, e) in self.segments]
                while not all(f.done() for f in futs):
                    self._tick()
                    time.sleep(0.3)
                for f in futs:            # 取出 worker 异常（没有就返回 None）
                    exc = f.exception()
                    if exc is not None:
                        raise exc
        finally:
            self.bytes_done = self.resume_base + self.counter.get()

    def _download_segment(self, idx, start, end, max_att):
        """下载 [start, end] 闭区间这一段，追加到自己的 .seg<i> 文件里。"""
        seg = self._seg_path(idx)
        seg_len = end - start + 1
        have = self._seg_have(idx)
        if have > seg_len:                 # 段文件比段还长：脏数据，弃之
            seg.unlink(missing_ok=True)
            have = 0
        pos = start + have
        attempt = 0
        while pos <= end:
            attempt += 1
            if attempt > max_att:
                raise RetryExhausted(f"分段 {idx} 重试 {max_att} 次仍未完成")
            try:
                headers = {"Range": f"bytes={pos}-{end}"}
                resp = self.session.get(self.url, headers=headers, stream=True,
                                        timeout=(self.s["timeout"], self.s["timeout"]))
                if resp.status_code == 200:
                    resp.close()
                    # 服务器忽略了 Range：分块模式无法定位，触发整体回退单流
                    raise RangeUnsupported("分段请求返回 200（服务器忽略 Range）")
                if resp.status_code == 416:
                    resp.close()
                    raise FatalError(f"分段 {idx} 收到 416（段范围非法）")
                if resp.status_code != 206:
                    resp.close()
                    self._raise_http(resp.status_code)
                with open(seg, "ab") as fh:
                    for chunk in resp.iter_content(CHUNK):
                        if not chunk:
                            continue
                        self.bucket.take(len(chunk))
                        fh.write(chunk)
                        pos += len(chunk)
                        self.counter.add(len(chunk))
                resp.close()
            except RangeUnsupported:
                raise
            except FatalError:
                raise
            except (requests.RequestException, OSError, RetryableHTTP) as exc:
                self._print(f"分段 {idx} 网络异常（第 {attempt}/{max_att} 次），退避重试: {exc}")
                self._backoff(attempt)
        # 段下载完成，pos == end + 1

    def _assemble(self):
        """分块模式：把各段按顺序拼成 .part 后删段文件；单流模式无事可做。"""
        if self.mode != "multi":
            return
        with open(self.part_path, "wb") as out:
            for (i, _s, _e) in self.segments:
                with open(self._seg_path(i), "rb") as fh:
                    shutil.copyfileobj(fh, out, 4 * 1024 * 1024)
        self._cleanup_segments()

    # -------------------------------------------------------------- 校验与收尾

    def _verify_and_promote(self, result):
        """整文件哈希 → 与期望值核对 → 通过才转正为最终文件名。"""
        hashes = utils.hash_file(self.part_path, ("sha256", "md5"))
        self.actual_sha256 = hashes["sha256"]
        result["actual_sha256"] = self.actual_sha256
        self._print(f"SHA256: {self.actual_sha256}")

        algo, expected = self.hash_algo, self.expected_hash
        source = "命令行"
        if not expected and self.s["auto_verify"]:
            sidecar = self.final_path.with_name(self.final_path.name + ".sha256")
            algo, expected = utils.parse_sha256_file(sidecar)
            source = f"sidecar {sidecar.name}" if algo else ""

        if expected:
            got = hashes[algo]
            ok = got == expected
            label = "SHA256" if algo == "sha256" else "MD5"
            if ok:
                self._print(f"{label} 校验通过（{source}）")
            else:
                self._print(f"{label} 校验失败（{source}）: 期望 {expected}，实得 {got}")
            result["note"] = f"{label} 校验" + ("通过" if ok else "失败")
        else:
            ok = True

        if not ok:
            corrupt = self.part_path.with_name(self.final_path.name + ".corrupt")
            os.replace(self.part_path, corrupt)   # 坏数据不能留着被反复续传
            self._print(f"坏数据已改名为: {corrupt}")
            raise FatalError("哈希校验失败")

        os.replace(self.part_path, self.final_path)
        self._print(f"文件保存到: {self.final_path}")
        return True

    # -------------------------------------------------------------- 进度落盘

    def _save_progress(self, result=None):
        if not self.progress_file:
            return
        state = prog.new_state(self.url, self.final_path.name if self.final_path else "", self.output_dir)
        old = prog.read(self.progress_file) or {}
        state.update(old)                       # 保留 started_at 等历史字段
        state.update({
            "status": (result or {}).get("status") or ("complete" if self.skipped else "downloading"),
            "bytes_done": (result or {}).get("bytes_total") if self.skipped else self.bytes_done,
            "bytes_total": self.bytes_total or 0,
            "mode": self.mode,
            "segments": [list(x) for x in self.segments],
            "resumable": bool(self.part_path and self.part_path.exists())
                         or self.mode == "multi",
            "expected_hash": self.expected_hash,
            "hash_algo": self.hash_algo,
            "actual_sha256": self.actual_sha256 or (old.get("actual_sha256") or ""),
            "error": (result or {}).get("error", ""),
            "note": (result or {}).get("note", old.get("note", "")),
            "path": str(self.final_path) if self.final_path else old.get("path", ""),
        })
        if (result or {}).get("status") in ("complete", "failed"):
            state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            prog.write(self.progress_file, state)
        except OSError:
            pass    # 进度落盘失败不影响下载本身
