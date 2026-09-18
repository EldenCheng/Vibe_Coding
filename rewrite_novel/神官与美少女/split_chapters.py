import re
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

input_file = "魔王神官与勇者美少女(改写_第74章~76章).txt"
output_dir = "."

cn_num_map = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    '十': 10, '百': 100, '千': 1000, '万': 10000,
}

def chinese_to_arabic(s):
    result = 0
    current = 0
    for ch in s:
        if ch in cn_num_map:
            val = cn_num_map[ch]
            if val >= 10:
                if current == 0:
                    current = 1
                result += current * val
                current = 0
            else:
                current = val
    result += current
    return result

with open(input_file, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.split('\n')
chapters = []
current_chapter_num = None
current_lines = []

pattern = re.compile(r'^第?一?部[分]?[ 　]第([\d零一二三四五六七八九十百千万]+)章[ 　]')

for line in lines:
    match = pattern.match(line)
    if match:
        if current_chapter_num is not None and current_lines:
            chapters.append((current_chapter_num, '\n'.join(current_lines)))
        num_str = match.group(1)
        current_chapter_num = int(num_str) if num_str.isdigit() else chinese_to_arabic(num_str)
        current_lines = [line]
    else:
        if current_chapter_num is not None:
            current_lines.append(line)

if current_chapter_num is not None and current_lines:
    chapters.append((current_chapter_num, '\n'.join(current_lines)))

print(f"Found {len(chapters)} chapters")

for num, text in chapters:
    filename = f"魔王神官与勇者美少女(改写_第{num}章).txt"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Written: {filename}")

print("Done!")
