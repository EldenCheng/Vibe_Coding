# -*- coding: utf-8 -*-
"""
pi 数据备份工具 v1.0.0
=======================
功能：备份 pi coding agent 的用户设置与会话数据，压缩存放为 zip。

运行方式：
    py backup_pi.py

输出：
    在本脚本所在目录的 backup/<当前日期>/ 下生成
    - pi_agent_备份_<日期>.zip    压缩备份包
    - 备份清单.txt                 备份内容清单

详细说明见《备份与恢复帮助.md》、《项目设计文档.md》。
"""

import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# ============================ 配置区 ============================
# pi 数据源目录：默认 ~/.pi/agent，可用环境变量 PI_CODING_AGENT_DIR 覆盖
DEFAULT_SOURCE = Path.home() / ".pi" / "agent"

# 需要排除的相对路径片段（命中即跳过，用于减小备份体积）
EXCLUDE_PATTERNS = [
    "bin",  # pi 自动下载的工具二进制（fd.exe），可重新获取，无需备份
]

# 输出根目录：本脚本所在目录下的 backup 文件夹
OUTPUT_ROOT = Path(__file__).resolve().parent / "backup"
# ================================================================


def get_source_dir() -> Path:
    """定位 pi 数据源目录：优先环境变量，其次默认路径。"""
    env = os.environ.get("PI_CODING_AGENT_DIR")
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p
        print(f"[警告] 环境变量 PI_CODING_AGENT_DIR 指向的目录不存在：{p}")
    if DEFAULT_SOURCE.is_dir():
        return DEFAULT_SOURCE
    print(f"[错误] 找不到 pi 数据目录：{DEFAULT_SOURCE}")
    print("请确认已安装并使用过 pi，或通过 PI_CODING_AGENT_DIR 指定正确目录。")
    sys.exit(1)


def is_excluded(rel_path: Path) -> bool:
    """判断相对路径是否命中排除规则。"""
    parts = rel_path.parts
    return any(pat in parts for pat in EXCLUDE_PATTERNS)


def collect_files(source_dir: Path):
    """
    遍历源目录，收集需要备份的文件。
    返回：[(绝对路径, 相对路径), ...]，按相对路径排序。
    """
    files = []
    for root, dirs, names in os.walk(source_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(source_dir)
        # 就地过滤目录，避免进入被排除的子目录
        dirs[:] = [d for d in dirs if not is_excluded(rel_root / d)]
        for name in names:
            abs_path = root_path / name
            rel_path = abs_path.relative_to(source_dir)
            if is_excluded(rel_path):
                continue
            files.append((abs_path, rel_path))
    return sorted(files, key=lambda item: str(item[1]))


def make_archive(files, date_dir: Path) -> tuple:
    """
    在日期目录下创建 zip 压缩包。
    返回：(zip 路径, 原始总大小, 压缩后总大小)。
    若当天已存在同名压缩包，则在文件名后追加时间，避免覆盖。
    """
    now = datetime.now()
    zip_name = f"pi_agent_备份_{now:%Y-%m-%d}.zip"
    zip_path = date_dir / zip_name
    if zip_path.exists():  # 同一天再次运行：加时间后缀，保留多份
        zip_name = f"pi_agent_备份_{now:%Y-%m-%d_%H-%M-%S}.zip"
        zip_path = date_dir / zip_name

    raw_total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, rel_path in files:
            # 以相对路径作为压缩包内路径，解压后结构与源目录一致，便于还原
            zf.write(abs_path, arcname=str(rel_path))
            raw_total += abs_path.stat().st_size

    compressed_total = zip_path.stat().st_size
    return zip_path, raw_total, compressed_total


def write_manifest(files, source_dir: Path, date_dir: Path,
                   zip_path: Path, raw_total: int, compressed_total: int) -> Path:
    """生成备份清单文件（UTF-8），便于日后核对备份内容。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ratio = (1 - compressed_total / raw_total) * 100 if raw_total else 0

    lines = [
        "pi 数据备份清单",
        "=" * 40,
        f"备份时间：{now}",
        f"数据源目录：{source_dir}",
        f"压缩包：{zip_path.name}",
        f"文件总数：{len(files)}",
        f"原始大小：{raw_total / 1024:.1f} KB",
        f"压缩大小：{compressed_total / 1024:.1f} KB",
        f"压缩率：节约 {ratio:.1f}%",
        "",
        "文件清单：",
    ]
    for abs_path, rel_path in files:
        lines.append(f"  {rel_path}  ({abs_path.stat().st_size} 字节)")

    manifest_path = date_dir / "备份清单.txt"
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    return manifest_path


def main():
    """主流程：定位源目录 -> 收集文件 -> 建立日期目录 -> 压缩 -> 写清单 -> 输出摘要。"""
    print("=" * 50)
    print("pi 数据备份工具 v1.0.0")
    print("=" * 50)

    source_dir = get_source_dir()
    files = collect_files(source_dir)
    if not files:
        print("[错误] 源目录中没有任何需要备份的文件。")
        sys.exit(1)

    # 建立日期目录：backup/YYYY-MM-DD/
    date_dir = OUTPUT_ROOT / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    print(f"数据源：{source_dir}")
    print(f"备份目录：{date_dir}")
    print(f"待备份文件数：{len(files)}")

    zip_path, raw_total, compressed_total = make_archive(files, date_dir)
    manifest_path = write_manifest(files, source_dir, date_dir,
                                   zip_path, raw_total, compressed_total)

    print()
    print("备份完成 ✔")
    print(f"  压缩包：{zip_path}")
    print(f"  清单：{manifest_path}")
    print(f"  原始 {raw_total / 1024:.1f} KB → 压缩后 {compressed_total / 1024:.1f} KB")


if __name__ == "__main__":
    main()
