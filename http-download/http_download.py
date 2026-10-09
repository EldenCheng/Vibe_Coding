# -*- coding: utf-8 -*-
"""HTTP 直链下载器 CLI 入口。

用法：
    py http_download.py [选项] <URL>

例：
    py http_download.py --sha256 76e450… --speed-limit 2048 https://…/big.zip
"""
import argparse
import os
import sys
from pathlib import Path

# 保证以任意 cwd 直接运行本脚本都能导入同目录的 http_down 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from http_down import engine, settings, utils  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(
        prog="http_download",
        description="HTTP(S) 直链文件下载器：断点续传 / 多线程分块 / 限速 / SHA256・MD5 校验")
    parser.add_argument("url", help="HTTP(S) 直链 URL")
    parser.add_argument("--config", help="config.json 路径（默认：脚本同目录下的 config.json）")
    parser.add_argument("--output-dir", help="输出目录（覆盖 config.json）")
    parser.add_argument("--proxy", help="代理地址，如 http://127.0.0.1:10808（覆盖 config.json）")
    parser.add_argument("--filename", help="指定保存文件名（默认自动解析）")
    parser.add_argument("--sha256", help="期望校验值：64 位 hex=SHA256，32 位 hex=MD5")
    parser.add_argument("--concurrency", type=int, help="分块并发数 1-16（覆盖 config.json）")
    parser.add_argument("--speed-limit", type=int, help="限速 KB/s，0=不限（覆盖 config.json）")
    parser.add_argument("--overwrite", choices=settings.OVERWRITE_CHOICES,
                        help="重名处理（覆盖 config.json）")
    parser.add_argument("--header", action="append", metavar="K: V",
                        help='附加请求头，可重复，如 --header "Referer: https://x/"')
    parser.add_argument("--max-attempts", type=int, help="单请求最大重试次数（覆盖 config.json）")
    return parser


def main(argv=None):
    # Windows 控制台默认 GBK：先把输出流掰成 UTF-8，避免中文乱码（与 e-download 同款自保）
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)

    try:
        cfg = settings.load_settings(args.config)
        settings.apply_cli(cfg, args)
    except settings.ConfigError as exc:
        print(f"配置错误: {exc}")
        return 1

    expected_hash, expected_algo = "", ""
    if args.sha256:
        expected_algo, expected_hash = utils.detect_hash_algo(args.sha256)
        if not expected_algo:
            print("校验值不合法: 需要 64 位（SHA256）或 32 位（MD5）十六进制字符串")
            return 1

    job = engine.DownloadJob(args.url, cfg, filename=args.filename,
                             expected_hash=expected_hash,
                             expected_algo=expected_algo)
    try:
        result = job.run()
    except KeyboardInterrupt:
        # run() 已把进度落盘；硬退出以终止仍在跑的 worker 线程（等效 Ctrl+C 的预期行为）
        os._exit(130)

    if result["status"] != "complete":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
