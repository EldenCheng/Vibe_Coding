import argparse
import re
import os
import shutil
import sys
from pathlib import Path
from difflib import SequenceMatcher


def parse_args():
    parser = argparse.ArgumentParser(
        description="统一视频文件与字幕文件的文件名，按对齐策略重命名字幕文件"
    )
    parser.add_argument("video_ext", help="视频文件扩展名，例如 .mp4 .mkv .avi")
    parser.add_argument("sub_ext", help="字幕文件扩展名，例如 .srt .ass .vtt")
    parser.add_argument(
        "--mode",
        choices=["number", "sequential", "fuzzy"],
        default="number",
        help="对齐模式：number（数字序号，默认）| sequential（顺序匹配）| fuzzy（模糊匹配）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际执行重命名",
    )
    return parser.parse_args()


def normalize_ext(ext: str) -> str:
    if not ext.startswith("."):
        ext = "." + ext
    return ext.lower()


def extract_numbers(name: str) -> tuple:
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums)


def natural_sort_key(name: str) -> list:
    parts = re.split(r"(\d+)", name)
    result = []
    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part.lower())
    return result


def fuzzy_match(video_list: list, sub_list: list, cutoff: float = 0.3) -> list:
    pairs = []
    used_subs = set()
    for v in video_list:
        best_sub = None
        best_ratio = 0
        v_stem = v.stem
        for si, s in enumerate(sub_list):
            if si in used_subs:
                continue
            s_stem = s.stem
            ratio = SequenceMatcher(None, v_stem, s_stem).ratio()
            if ratio > best_ratio and ratio >= cutoff:
                best_ratio = ratio
                best_sub = si
        if best_sub is not None:
            pairs.append((v, sub_list[best_sub]))
            used_subs.add(best_sub)
        else:
            pairs.append((v, None))
    return pairs


def main():
    args = parse_args()
    video_ext = normalize_ext(args.video_ext)
    sub_ext = normalize_ext(args.sub_ext)
    mode = args.mode

    cwd = Path.cwd()

    video_files = sorted(
        [f for f in cwd.iterdir() if f.is_file() and f.suffix.lower() == video_ext],
        key=lambda x: x.name.lower(),
    )
    sub_files = sorted(
        [f for f in cwd.iterdir() if f.is_file() and f.suffix.lower() == sub_ext],
        key=lambda x: x.name.lower(),
    )

    if not video_files:
        print(f"未找到任何 {video_ext} 视频文件")
        sys.exit(1)
    if not sub_files:
        print(f"未找到任何 {sub_ext} 字幕文件")
        sys.exit(1)

    print(f"找到 {len(video_files)} 个视频文件, {len(sub_files)} 个字幕文件")
    print(f"对齐模式: {mode}")
    print()

    sub_set = {(s.stem, s.suffix.lower()) for s in sub_files}

    already_matched_subs = []
    video_to_align = []
    for v in video_files:
        if (v.stem, sub_ext) in sub_set:
            for s in sub_files:
                if s.stem == v.stem and s.suffix.lower() == sub_ext:
                    already_matched_subs.append(s)
                    break
        else:
            video_to_align.append(v)

    sub_to_align = [s for s in sub_files if s not in already_matched_subs]

    if already_matched_subs:
        print(f"已对齐（跳过）: {len(already_matched_subs)} 个视频已存在匹配字幕")
        print()

    if not video_to_align:
        print("所有视频均已对齐，无需操作")
        return

    print(f"待对齐: {len(video_to_align)} 个视频, {len(sub_to_align)} 个字幕")
    print()

    if mode == "number":
        video_sorted = sorted(video_to_align, key=lambda f: extract_numbers(f.stem))
        sub_sorted = sorted(sub_to_align, key=lambda f: extract_numbers(f.stem))
        pairs = list(zip(video_sorted, sub_sorted))
        if len(video_sorted) != len(sub_sorted):
            print(
                f"警告: 视频文件数({len(video_sorted)})与字幕文件数({len(sub_sorted)})不一致"
            )
            print()
    elif mode == "sequential":
        pairs = list(zip(video_to_align, sub_to_align))
        if len(video_to_align) != len(sub_to_align):
            print(
                f"警告: 视频文件数({len(video_to_align)})与字幕文件数({len(sub_to_align)})不一致"
            )
            print()
    elif mode == "fuzzy":
        pairs = fuzzy_match(video_to_align, sub_to_align)
        unmatched = [v for v, s in pairs if s is None]
        if unmatched:
            print(f"警告: 以下 {len(unmatched)} 个视频未能找到匹配的字幕:")
            for v in unmatched:
                print(f"  {v.name}")
            print()

    rename_count = 0
    skip_count = 0
    bak_dir = None
    for video, sub in pairs:
        if sub is None:
            continue
        new_name = video.stem + sub_ext
        if sub.name.lower() == new_name.lower():
            print(f"[跳过] 名称已相同: {sub.name}")
            skip_count += 1
            continue
        target_path = sub.with_name(new_name)
        if target_path.exists():
            print(f"[跳过] 目标文件已存在: {new_name}")
            skip_count += 1
            continue
        print(f"[重命名] {sub.name} -> {new_name}")
        if not args.dry_run:
            if bak_dir is None:
                bak_dir = cwd / "sub_bak"
                bak_dir.mkdir(exist_ok=True)
            shutil.copy2(sub, bak_dir / sub.name)
            sub.rename(target_path)
            rename_count += 1
        else:
            rename_count += 1

    print()
    print(f"完成: 重命名 {rename_count} 个, 跳过 {skip_count} 个")


if __name__ == "__main__":
    main()
