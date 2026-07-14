import sys
from pathlib import Path

RE_PREFIX = "[重命名] "


def main():
    if len(sys.argv) < 2:
        print("用法: python undo_rename.py <log_file>")
        print("      将 log 文本保存到文件, 脚本按行解析 [重命名] 记录并逆向还原")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    if not log_path.is_file():
        print(f"文件不存在: {log_path}")
        sys.exit(1)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    pairs = []
    for line in lines:
        if not line.startswith(RE_PREFIX):
            continue
        rest = line[len(RE_PREFIX):]
        if " -> " not in rest:
            continue
        original, current = rest.split(" -> ", 1)
        pairs.append((original.strip(), current.strip()))

    if not pairs:
        print("未找到任何 [重命名] 记录")
        return

    cwd = Path.cwd()
    restored = 0
    skipped = 0

    for original, current in reversed(pairs):
        src = cwd / current
        dst = cwd / original
        if not src.exists():
            print(f"[跳过] 当前文件不存在: {current}")
            skipped += 1
            continue
        if dst.exists():
            print(f"[跳过] 目标文件已存在: {original}")
            skipped += 1
            continue
        print(f"[还原] {current} -> {original}")
        src.rename(dst)
        restored += 1

    print()
    print(f"完成: 还原 {restored} 个, 跳过 {skipped} 个")


if __name__ == "__main__":
    main()
