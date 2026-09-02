#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
漫画管理器 - 主扫描脚本

扫描本地漫画目录，生成可离线浏览的HTML页面。
"""

import os
import re
import json
import shutil
from datetime import datetime
from pathlib import Path

import config


def extract_sort_key(filename):
    """
    从文件名中提取章节编号作为排序键。
    
    策略：
    1. 去掉 [xxx][xxx] 前缀和 .kepub.epub/.epub 后缀
    2. 用正则 re.findall(r'\\d+', name) 提取所有数字
    3. 取第一个数字作为 sort_key
    4. 如果无数字，sort_key = None
    """
    # 去掉 [xxx][xxx] 前缀
    name = re.sub(r'^\[.*?\]\[.*?\]', '', filename)
    # 去掉 .kepub.epub 或 .epub 后缀
    name = re.sub(r'\.(kepub\.)?epub$', '', name)
    # 提取所有数字
    numbers = re.findall(r'\d+', name)
    if numbers:
        return int(numbers[0])
    return None


def format_size(size_bytes):
    """将字节大小格式化为可读字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def parse_folder_name(folder_name):
    """
    解析文件夹名，提取状态、彩色、显示名等属性。
    
    返回字典：
    - display_name: 显示名（去掉标记）
    - status: 状态（完结/连载中/停更）
    - colored: 是否彩色
    """
    status = "连载中"  # 默认状态
    colored = False
    display_name = folder_name
    
    # 检查彩色标记
    if "全彩" in folder_name or "彩色" in folder_name:
        colored = True
    
    # 提取括号内容
    bracket_match = re.search(r'\(([^)]+)\)$', folder_name)
    if bracket_match:
        bracket_content = bracket_match.group(1)
        
        # 状态判断优先级：停更 > 未完 > 完
        if "停更" in bracket_content:
            status = "停更"
        elif "未完" in bracket_content:
            status = "连载中"
        elif "完" in bracket_content:
            status = "完结"
        
        # 去掉状态、彩色、范围等标记
        # 这些标记都在括号内，去掉整个括号内容
        display_name = re.sub(r'\([^)]*\)$', '', folder_name).strip()
    
    return {
        "display_name": display_name,
        "status": status,
        "colored": colored
    }


def get_file_info(filepath):
    """获取文件信息（大小、修改时间）"""
    stat = os.stat(filepath)
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime
    }


def scan_manga_directory(manga_root):
    """
    扫描漫画根目录，返回所有漫画的信息列表。
    """
    manga_list = []
    
    # 检查目录是否存在
    if not os.path.exists(manga_root):
        print(f"错误：漫画目录不存在 - {manga_root}")
        return manga_list
    
    # 遍历所有子目录
    for folder_name in os.listdir(manga_root):
        folder_path = os.path.join(manga_root, folder_name)
        
        # 只处理目录
        if not os.path.isdir(folder_path):
            continue
        
        # 解析文件夹名
        folder_info = parse_folder_name(folder_name)
        
        # 扫描目录内的epub文件
        chapters = []
        latest_mtime = 0
        total_size = 0
        
        for file_name in os.listdir(folder_path):
            # 检查文件扩展名
            if file_name.endswith('.kepub.epub'):
                ext = '.kepub.epub'
            elif file_name.endswith('.epub'):
                ext = '.epub'
            else:
                continue
            
            file_path = os.path.join(folder_path, file_name)
            
            # 获取文件信息
            file_info = get_file_info(file_path)
            
            # 提取章节名称（去掉扩展名）
            chapter_name = file_name[:-len(ext)]
            
            # 提取排序键
            sort_key = extract_sort_key(file_name)
            
            # 添加到章节列表
            chapters.append({
                "name": chapter_name,
                "sort_key": sort_key,
                "size": file_info["size"],
                "mtime": file_info["mtime"]
            })
            
            # 更新最新修改时间
            if file_info["mtime"] > latest_mtime:
                latest_mtime = file_info["mtime"]
            
            # 累加总大小
            total_size += file_info["size"]
        
        # 如果没有章节，跳过
        if not chapters:
            continue
        
        # 按 sort_key 排序（None 放在最后）
        chapters.sort(key=lambda x: (x["sort_key"] is None, x["sort_key"] or 0))
        
        # 获取最新章节
        latest_chapter = chapters[-1]["name"] if chapters else None
        latest_sort_key = chapters[-1]["sort_key"] if chapters else None
        
        # 构建漫画信息
        manga_info = {
            "name": folder_name,
            "display_name": folder_info["display_name"],
            "path": f"manga/{folder_name}.html",
            "status": folder_info["status"],
            "colored": folder_info["colored"],
            "latest_chapter": latest_chapter,
            "latest_sort_key": latest_sort_key,
            "update_time": datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d"),
            "update_timestamp": latest_mtime,
            "chapter_count": len(chapters),
            "total_size": format_size(total_size),
            "chapters": chapters
        }
        
        manga_list.append(manga_info)
    
    return manga_list


def generate_index_html(manga_list, template_path, output_path):
    """生成首页HTML"""
    # 读取模板
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # 准备数据（不包含chapters，因为首页不需要）
    index_data = []
    for manga in manga_list:
        index_data.append({
            "name": manga["name"],
            "display_name": manga["display_name"],
            "path": manga["path"],
            "status": manga["status"],
            "colored": manga["colored"],
            "latest_chapter": manga["latest_chapter"],
            "latest_sort_key": manga["latest_sort_key"],
            "update_time": manga["update_time"],
            "update_timestamp": manga["update_timestamp"],
            "chapter_count": manga["chapter_count"],
            "total_size": manga["total_size"]
        })
    
    # 替换占位符
    json_data = json.dumps(index_data, ensure_ascii=False, indent=2)
    html = template.replace('/*MANGA_DATA_PLACEHOLDER*/[]', json_data)
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"已生成首页: {output_path}")


def generate_manga_html(manga_info, template_path, output_dir):
    """生成漫画详情页HTML"""
    # 读取模板
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # 准备漫画信息（不包含chapters）
    manga_data = {
        "name": manga_info["name"],
        "display_name": manga_info["display_name"],
        "status": manga_info["status"],
        "colored": manga_info["colored"],
        "chapter_count": manga_info["chapter_count"],
        "total_size": manga_info["total_size"]
    }
    
    # 准备章节数据（格式化大小）
    chapters_data = []
    for chapter in manga_info["chapters"]:
        chapters_data.append({
            "name": chapter["name"],
            "sort_key": chapter["sort_key"],
            "size": format_size(chapter["size"])
        })
    
    # 替换占位符
    manga_json = json.dumps(manga_data, ensure_ascii=False, indent=2)
    chapters_json = json.dumps(chapters_data, ensure_ascii=False, indent=2)
    
    html = template.replace('/*MANGA_INFO_PLACEHOLDER*/{}', manga_json)
    html = html.replace('/*CHAPTERS_PLACEHOLDER*/[]', chapters_json)
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 写入文件
    output_path = os.path.join(output_dir, f"{manga_info['name']}.html")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"已生成详情页: {output_path}")


def main():
    """主函数"""
    print("漫画管理器 - 开始扫描...")
    print(f"漫画目录: {config.MANGA_ROOT}")
    print(f"输出目录: {config.OUTPUT_DIR}")
    print()
    
    # 获取脚本所在目录
    script_dir = Path(__file__).parent
    
    # 扫描漫画目录
    manga_list = scan_manga_directory(config.MANGA_ROOT)
    print(f"共找到 {len(manga_list)} 本漫画")
    print()
    
    if not manga_list:
        print("没有找到任何漫画，请检查目录配置。")
        return
    
    # 创建输出目录
    output_dir = script_dir / config.OUTPUT_DIR
    manga_output_dir = output_dir / "manga"
    os.makedirs(manga_output_dir, exist_ok=True)
    
    # 模板路径
    index_template = script_dir / "templates" / "index_template.html"
    manga_template = script_dir / "templates" / "manga_template.html"
    
    # 生成首页
    index_output = output_dir / "index.html"
    generate_index_html(manga_list, index_template, index_output)
    
    # 生成详情页
    print()
    print("正在生成漫画详情页...")
    for manga in manga_list:
        generate_manga_html(manga, manga_template, manga_output_dir)
    
    print()
    print("扫描完成！")
    print(f"请在浏览器中打开 {index_output} 查看漫画列表。")


if __name__ == "__main__":
    main()