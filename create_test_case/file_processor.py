"""
文件类型处理模块

负责检测文件类型，分发到对应处理函数：
- PDF: 调用pdf_converter转成图片
- 图片: 原样复制到outputs目录
- 不支持的格式: 输出错误信息
"""

import os
import sys
import shutil
from pdf_converter import convert_pdf_to_images

# 解决 Windows 控制台中文打印乱码问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


# 支持的文件扩展名
PDF_EXTENSIONS = [".pdf"]
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".bmp", ".gif"]
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS + IMAGE_EXTENSIONS

# 不支持的文件扩展名（用于提示用户）
UNSUPPORTED_EXTENSIONS = [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]


def detect_file_type(file_path):
    """
    检测文件类型

    :param file_path: 文件路径
    :return: 文件类型字符串 "pdf" / "image" / "unsupported"
    """
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext in PDF_EXTENSIONS:
        return "pdf"
    elif ext in IMAGE_EXTENSIONS:
        return "image"
    else:
        return "unsupported"


def process_file(file_path, output_dir):
    """
    处理文件，根据类型分发到对应处理函数

    :param file_path: 输入文件路径
    :param output_dir: 输出目录（如outputs/images/）
    :return: 是否处理成功
    """
    file_type = detect_file_type(file_path)

    if file_type == "pdf":
        # PDF：调用pdf_converter转成图片
        print(f"检测到PDF文件，正在转换为图片...")
        return convert_pdf_to_images(file_path, output_dir)

    elif file_type == "image":
        # 图片：原样复制到output_dir
        print(f"检测到图片文件，正在复制到输出目录...")
        return _copy_image(file_path, output_dir)

    else:
        # 不支持的格式
        print(f"错误: 不支持的文件类型")
        print(f"支持的文件格式: {', '.join(SUPPORTED_EXTENSIONS)}")
        print(f"暂不支持的格式: {', '.join(UNSUPPORTED_EXTENSIONS)}")
        return False


def _copy_image(image_path, output_dir):
    """
    将图片文件复制到输出目录

    :param image_path: 图片文件路径
    :param output_dir: 输出目录
    :return: 是否复制成功
    """
    try:
        # 如果输出目录不存在，则创建
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"创建目录: {output_dir}")

        # 获取文件名
        filename = os.path.basename(image_path)
        dest_path = os.path.join(output_dir, filename)

        # 复制文件
        shutil.copy2(image_path, dest_path)
        print(f"已复制图片: {filename}")
        return True

    except Exception as e:
        print(f"复制图片时出错: {e}")
        return False
