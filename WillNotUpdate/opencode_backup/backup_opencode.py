# -*- coding: utf-8 -*-
"""
opencode 数据备份脚本
=====================

功能:
  1. 自动探测 opencode 的数据目录与配置目录(检查多个典型位置)
  2. 按数据类型(数据库 / 配置 / 日志 / 快照)分别打包压缩
  3. 压缩文件放入备份根目录下以日期命名的子目录(YYYY-MM-DD)
  4. 数据库使用 sqlite 在线备份 API 保证一致性(自动合并 WAL)

用法:
  py backup_opencode.py

依赖:
  仅使用 Python 标准库;若本机安装了 7-Zip 则优先使用(压缩率高),
  否则自动回退为 zipfile 打包(.zip)。

更多说明见同目录下的 项目设计文档.md。
"""

import datetime
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


# ==================== 配置(可按需调整) ====================

# 备份根目录(脚本所在目录下的 backups)
BACKUP_ROOT = Path(__file__).resolve().parent / "backups"

# 7-Zip 可执行文件候选路径(脚本按顺序尝试)
SEVEN_ZIP_CANDIDATES = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]

# 数据目录探测顺序(特征:包含 opencode.db)
DATA_DIR_CANDIDATES = [
    Path.home() / ".local" / "share" / "opencode",
    Path(os.environ.get("LOCALAPPDATA", "")) / "opencode",
    Path(os.environ.get("APPDATA", "")) / "opencode",
]

# 配置目录探测顺序(特征:包含 opencode.jsonc)
CONFIG_DIR_CANDIDATES = [
    Path.home() / ".config" / "opencode",
    Path(os.environ.get("APPDATA", "")) / "opencode",
]

# 7z 压缩级别(1-9,越大压缩率越高、越慢)
SEVEN_ZIP_LEVEL = 5


# ==================== 工具探测 ====================

def find_seven_zip():
    """寻找 7-Zip 可执行文件,找到返回路径,否则返回 None。"""
    # 优先检查候选固定路径
    for cand in SEVEN_ZIP_CANDIDATES:
        if Path(cand).is_file():
            return cand
    # 其次检查 PATH 中是否有 7z
    found = __import__("shutil").which("7z")
    return found


def find_dirs():
    """探测数据目录与配置目录,返回 (data_dir, config_dir) 或 (None, None)。

    探测逻辑:按候选顺序找到"包含标志文件"的目录即视为命中。
    """
    data_dir = None
    for cand in DATA_DIR_CANDIDATES:
        if cand.is_dir() and (cand / "opencode.db").is_file():
            data_dir = cand
            break
    config_dir = None
    for cand in CONFIG_DIR_CANDIDATES:
        if cand.is_dir() and (cand / "opencode.jsonc").is_file():
            config_dir = cand
            break
    return data_dir, config_dir


# ==================== 数据库一致性副本 ====================

def copy_db_consistent(src_db, dest_db):
    """使用 sqlite 在线备份 API 生成一致性副本(自动合并 WAL)。

    源库正在被 opencode 使用时也安全。失败时抛异常交由调用方处理。
    """
    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest_db)
        try:
            with dst:
                src.backup(dst)  # 将源库(含未落盘 WAL)复制到目标
        finally:
            dst.close()
    finally:
        src.close()


# ==================== 压缩实现 ====================

def _decode_output(data):
    """解码 7-Zip 的输出。7z 使用系统本地代码页,UTF-8 解码可能失败。"""
    if not data:
        return ""
    # 依次尝试常见编码,均失败则用 replace 兜底
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def compress_with_seven_zip(archive_path, cwd, sources, seven_zip):
    """使用 7-Zip 压缩。sources 为相对 cwd 的文件/目录名列表。"""
    cmd = [
        seven_zip, "a", "-y", f"-mx={SEVEN_ZIP_LEVEL}",
        str(archive_path), *sources,
    ]
    # 以字节方式捕获输出,避免 7z 本地代码页输出导致解码崩溃
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True)
    err = _decode_output(proc.stderr or proc.stdout)
    return proc.returncode == 0, err


def compress_with_zipfile(archive_path, cwd, sources):
    """回退方案:使用标准库 zipfile 压缩。sources 相对 cwd。"""
    archive_path = Path(str(archive_path).replace(".7z", ".zip"))
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for source in sources:
            src_path = cwd / source
            if src_path.is_dir():
                # 压缩整个目录,保持相对结构(如 log/xxx.log)
                for file in sorted(src_path.rglob("*")):
                    if file.is_file():
                        arc = file.relative_to(cwd).as_posix()
                        zf.write(file, arc)
            elif src_path.is_file():
                # 单文件,压缩包内只保留文件名
                zf.write(src_path, src_path.name)
    return archive_path


def make_archive(archive_path, cwd, sources, seven_zip):
    """统一压缩入口:7-Zip 优先,失败回退 zipfile。

    返回 (最终归档路径, 是否使用7z)。
    """
    if seven_zip:
        ok, err = compress_with_seven_zip(archive_path, cwd, sources, seven_zip)
        if ok:
            return archive_path, True
        print(f"  [警告] 7-Zip 压缩失败,回退 zipfile:{err.strip()[:200]}")
        # 删除 7z 失败时可能产生的半成品归档
        archive_path.unlink(missing_ok=True)
    return compress_with_zipfile(archive_path, cwd, sources), False


# ==================== 备份主流程 ====================

def clean_old_archives(backup_dir, key):
    """清理某类别可能残留的旧归档(.7z 与 .zip),避免同日期重跑后混合遗留。"""
    for ext in (".7z", ".zip"):
        (backup_dir / f"{key}{ext}").unlink(missing_ok=True)


def backup_file_category(key, cwd, source, backup_dir, seven_zip):
    """备份单个文件(如 opencode.jsonc)。"""
    src_path = cwd / source
    if not src_path.is_file():
        print(f"[跳过] {key}:源文件不存在 {src_path}")
        return None
    archive = backup_dir / f"{key}.7z"
    clean_old_archives(backup_dir, key)
    print(f"[备份] {key}: {src_path} -> {archive}")
    final, used_7z = make_archive(archive, cwd, [source], seven_zip)
    ext = "7z" if used_7z else "zip"
    return final, ext


def backup_dir_category(key, cwd, source, backup_dir, seven_zip):
    """备份整个目录(如 log/、snapshot/)。"""
    src_path = cwd / source
    if not src_path.is_dir() or not any(src_path.rglob("*")):
        print(f"[跳过] {key}:目录为空或不存在 {src_path}")
        return None
    archive = backup_dir / f"{key}.7z"
    clean_old_archives(backup_dir, key)
    print(f"[备份] {key}: {src_path} -> {archive}")
    final, used_7z = make_archive(archive, cwd, [source], seven_zip)
    ext = "7z" if used_7z else "zip"
    return final, ext


def backup_db_category(data_dir, backup_dir, seven_zip, tmp_root):
    """备份数据库:先做一致性副本,再压缩。"""
    db_file = data_dir / "opencode.db"
    if not db_file.is_file():
        print(f"[跳过] opencode.db:数据库不存在 {db_file}")
        return None
    archive = backup_dir / "opencode.db.7z"
    clean_old_archives(backup_dir, "opencode.db")
    print(f"[备份] opencode.db:{db_file}(含 session 记录)-> {archive}")

    # 1. 生成一致性临时副本(合并 WAL)
    tmp_dir = Path(tempfile.mkdtemp(dir=tmp_root, prefix="opencode_db_"))
    tmp_db = tmp_dir / "opencode.db"
    try:
        print("  ... 正在通过 sqlite 在线备份生成一致性副本(耗时较长)")
        copy_db_consistent(db_file, tmp_db)
        # 2. 压缩副本(工作目录指向临时目录,包内只含裸文件名)
        if seven_zip:
            cmd = [
                seven_zip, "a", "-y", f"-mx={SEVEN_ZIP_LEVEL}",
                str(archive), "opencode.db",
            ]
            proc = subprocess.run(cmd, cwd=str(tmp_dir), capture_output=True)
            if proc.returncode == 0:
                return archive, "7z"
            err = _decode_output(proc.stderr or proc.stdout)
            print(f"  [警告] 7-Zip 压缩失败,回退 zipfile:{err.strip()[:200]}")
            archive.unlink(missing_ok=True)
        # zipfile 回退
        final = archive.with_suffix(".zip")
        with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, "opencode.db")
        return final, "zip"
    finally:
        # 清理临时目录
        try:
            shutil_rmtree(tmp_dir)
        except Exception:
            pass


def shutil_rmtree(path):
    """删除目录树(带错误容错)。"""
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def main():
    """主流程入口。"""
    print("=" * 60)
    print("opencode 数据备份")
    print("=" * 60)

    # 1. 探测压缩工具
    seven_zip = find_seven_zip()
    if seven_zip:
        print(f"[工具] 使用 7-Zip:{seven_zip}")
    else:
        print("[工具] 未找到 7-Zip,回退为 Python zipfile 打包")

    # 2. 探测目录
    data_dir, config_dir = find_dirs()
    if not data_dir and not config_dir:
        print("[错误] 未找到 opencode 的数据/配置目录,无法备份。")
        sys.exit(1)
    if data_dir:
        print(f"[目录] 数据目录:{data_dir}")
    if config_dir:
        print(f"[目录] 配置目录:{config_dir}")

    # 3. 创建日期备份目录
    today = datetime.date.today().isoformat()
    backup_dir = BACKUP_ROOT / today
    backup_dir.mkdir(parents=True, exist_ok=True)
    print(f"[输出] 备份目录:{backup_dir}")

    results = []
    tmp_root = Path(tempfile.gettempdir()) / "opencode_backup_tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    # 4. 依次备份各类数据
    try:
        if config_dir:
            r = backup_file_category(
                "opencode.jsonc", config_dir, "opencode.jsonc", backup_dir, seven_zip)
            if r:
                results.append(r)
        if data_dir:
            r = backup_db_category(data_dir, backup_dir, seven_zip, tmp_root)
            if r:
                results.append(r)
            r = backup_dir_category("log", data_dir, "log", backup_dir, seven_zip)
            if r:
                results.append(r)
            r = backup_dir_category("snapshot", data_dir, "snapshot", backup_dir, seven_zip)
            if r:
                results.append(r)
    finally:
        shutil_rmtree(tmp_root)

    # 5. 输出摘要
    print("-" * 60)
    print("备份完成,共 %d 项:" % len(results))
    for archive, ext in results:
        size_mb = archive.stat().st_size / 1024 / 1024
        print(f"  {archive.name} ({size_mb:.1f} MB)")

    # 提示跳过项
    print("[提示] auth.json(含凭证)不在备份范围内;storage/ tool-output/ repos/ 为空已跳过。")


if __name__ == "__main__":
    main()
