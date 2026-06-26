"""
PDF转图片模块

使用PyMuPDF将PDF的每一页转换为JPG图片
"""

import os
import sys
import fitz  # PyMuPDF

# 解决 Windows 控制台中文打印乱码问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def convert_pdf_to_images(pdf_path, output_dir):
    """
    将PDF的每一页转换为图片（JPG格式）

    :param pdf_path: PDF文件路径
    :param output_dir: 图片保存目录
    :return: 是否转换成功
    """
    # 如果输出目录不存在，则创建
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建目录: {output_dir}")

    try:
        # 打开PDF文件
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        print(f"正在处理PDF: {pdf_path} (共 {total_pages} 页)")

        for page_index in range(total_pages):
            page = doc.load_page(page_index)
            # 获取页面像素图（使用2倍缩放确保清晰度）
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))

            # 生成图片文件名（从1开始编号）
            image_filename = f"page_{page_index + 1}.jpg"
            image_path = os.path.join(output_dir, image_filename)

            # 保存图片
            pix.save(image_path)
            print(f"已保存第 {page_index + 1}/{total_pages} 页: {image_filename}")

        doc.close()
        print(f"PDF转图片完成，共转换 {total_pages} 页")
        return True

    except Exception as e:
        print(f"转换PDF时出错: {e}")
        return False
