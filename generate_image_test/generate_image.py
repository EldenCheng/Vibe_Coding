"""
Agnes Image 2.1 Flash 图片生成脚本

功能:
- 调用 Agnes Image 2.1 Flash API 生成图片
- 支持 URL 输出模式
- 自动下载并保存图片到本地目录
- 命令行参数配置

API文档: https://agnes-ai.com/zh-Hans/docs/agnes-image-21-flash

使用方法:
    py generate_image.py --prompt "一只可爱的猫咪在草地上玩耍"
    py generate_image.py --prompt "A sunset over the ocean" --size 2K --ratio 16:9
    py generate_image.py --prompt "风景图" --output custom_output
"""

import argparse
import os
import sys
import requests
import time
from pathlib import Path
from datetime import datetime


api_key = os.getenv('AGNES_API_KEY')

# API 配置
API_URL = "https://apihub.agnes-ai.com/v1/images/generations"
MODEL_NAME = "agnes-image-2.1-flash"
ENV_API_KEY = "AGNES_API_KEY"

# 支持的尺寸档位
SUPPORTED_SIZES = ["1K", "2K", "3K", "4K"]

# 支持的宽高比
SUPPORTED_RATIOS = ["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"]


def get_api_key():
    """从环境变量获取 API Key"""
    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        print(f"错误: 未找到环境变量 {ENV_API_KEY}")
        print("请先设置 API Key:")
        print(f"  Windows (PowerShell): $env:{ENV_API_KEY}='your_api_key'")
        print(f"  Windows (CMD): set {ENV_API_KEY}=your_api_key")
        print(f"  Linux/Mac: export {ENV_API_KEY}='your_api_key'")
        sys.exit(1)
    return api_key


def build_prompt_key(prompt, max_len=20):
    """从提示词中提取关键词作为文件名的一部分"""
    # 移除特殊字符和空格,取前max_len个字符
    clean_chars = []
    for char in prompt:
        if char.isalnum() or char == '_':
            clean_chars.append(char)
        elif clean_chars:
            clean_chars.append('_')
    
    key = ''.join(clean_chars)[:max_len]
    return key if key else 'image'


def generate_image(prompt, size="1K", ratio="1:1"):
    """调用 Agnes Image API 生成图片"""
    if size not in SUPPORTED_SIZES:
        print(f"错误: 不支持的尺寸 '{size}'")
        print(f"支持的尺寸: {', '.join(SUPPORTED_SIZES)}")
        sys.exit(1)
    
    if ratio not in SUPPORTED_RATIOS:
        print(f"错误: 不支持的宽高比 '{ratio}'")
        print(f"支持的宽高比: {', '.join(SUPPORTED_RATIOS)}")
        sys.exit(1)
    
    api_key = get_api_key()
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "size": size,
        "ratio": ratio,
        "extra_body": {
            "response_format": "url"
        }
    }
    
    print(f"正在生成图片...")
    print(f"  模型: {MODEL_NAME}")
    print(f"  尺寸: {size}, 宽高比: {ratio}")
    print(f"  提示词: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=360)
        response.raise_for_status()
        
        result = response.json()
        
        if "data" not in result or len(result["data"]) == 0:
            print("错误: API 返回的数据为空")
            print(f"完整响应: {result}")
            sys.exit(1)
        
        image_url = result["data"][0].get("url")
        if not image_url:
            print("错误: 未能从 API 响应中获取图片URL")
            print(f"完整响应: {result}")
            sys.exit(1)
        
        return image_url
        
    except requests.exceptions.Timeout:
        print("错误: 请求超时,图片生成可能需要较长时间")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"错误: HTTP 请求失败 - {e}")
        try:
            error_detail = response.json()
            print(f"API 错误信息: {error_detail}")
        except:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"错误: 请求失败 - {e}")
        sys.exit(1)


def download_image(image_url, save_dir):
    """下载图片到指定目录"""
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    try:
        response = requests.get(image_url, timeout=60)
        response.raise_for_status()
        
        data = response.content
        
        file_ext = ".png"
        if b'\xff\xd8\xff' in data[:3]:
            file_ext = ".jpg"
        
        filename = f"{timestamp}{file_ext}"
        filepath = save_dir / filename
        
        with open(filepath, "wb") as f:
            f.write(data)
        
        return filepath
        
    except Exception as e:
        print(f"错误: 图片下载失败 - {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="使用 Agnes Image 2.1 Flash 生成图片")
    parser.add_argument("--prompt", required=True, help="图片生成的文本描述")
    parser.add_argument("--size", default="1K", choices=SUPPORTED_SIZES, help="输出尺寸档位 (默认: 1K)")
    parser.add_argument("--ratio", default="1:1", choices=SUPPORTED_RATIOS, help="宽高比 (默认: 1:1)")
    parser.add_argument("--output", default=None, help="输出目录 (默认: images/)")
    
    args = parser.parse_args()
    
    output_dir = args.output or os.path.join(os.getcwd(), "images")
    
    print("="*50)
    print("Agnes Image 2.1 Flash - 图片生成工具")
    print("="*50)
    
    image_url = generate_image(args.prompt, args.size, args.ratio)
    print(f"图片URL: {image_url[:80]}...")
    
    filepath = download_image(image_url, output_dir)
    
    print("="*50)
    print(f"图片已保存: {filepath}")
    print(f"文件大小: {os.path.getsize(filepath)} bytes")
    print("="*50)


if __name__ == "__main__":
    main()
