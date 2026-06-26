"""
分析处理模块

负责逐个读取图片，调API生成分析结果（markdown格式）
支持独立运行和被main.py调用两种方式
"""

import os
import sys
import argparse

# 解决 Windows 控制台中文打印乱码问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


class AnalysisProcessor:
    """分析处理器，负责将图片逐个发送给大模型进行分析"""

    def __init__(self, api_client, prompt_manager):
        """
        初始化分析处理器

        :param api_client: API客户端实例
        :param prompt_manager: 提示词管理器实例
        """
        self.api_client = api_client
        self.prompt_manager = prompt_manager

    def process_images(self, images_dir, output_dir, optional_prompts=None, temp_prompt=None):
        """
        逐个读取图片，调API生成分析结果

        :param images_dir: 图片目录（如outputs/images/）
        :param output_dir: 分析结果输出目录（如outputs/analysis/）
        :param optional_prompts: 可选提示词名称列表
        :param temp_prompt: 临时提示词内容
        :return: 是否全部成功
        """
        # 如果输出目录不存在，则创建
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"创建目录: {output_dir}")

        # 获取所有图片文件（按文件名排序）
        image_files = sorted([
            f for f in os.listdir(images_dir)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif'))
        ])

        if not image_files:
            print(f"错误: 在目录 {images_dir} 中未找到图片文件")
            return False

        # 构建提示词组合
        prompt = self.prompt_manager.build_analysis_prompt(optional_prompts, temp_prompt)

        total_files = len(image_files)
        success_count = 0
        fail_count = 0

        print(f"开始分析处理，共 {total_files} 个图片文件")

        for i, image_filename in enumerate(image_files, 1):
            image_path = os.path.join(images_dir, image_filename)
            # 生成对应的markdown文件名
            md_filename = os.path.splitext(image_filename)[0] + ".md"
            md_path = os.path.join(output_dir, md_filename)

            print(f"\n[{i}/{total_files}] 正在分析: {image_filename}")

            # 调用API分析图片
            result = self.api_client.analyze_image(image_path, prompt)

            if result:
                # 将结果保存为markdown文件
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(result)
                print(f"成功生成: {md_filename}")
                success_count += 1
            else:
                print(f"警告: {image_filename} 分析失败，跳过该文件")
                fail_count += 1

        print(f"\n分析处理完成: 成功 {success_count} 个，失败 {fail_count} 个")
        return fail_count == 0


def main():
    """独立运行入口"""
    parser = argparse.ArgumentParser(description="分析处理工具 - 逐个读取图片，调API生成分析结果")
    parser.add_argument("--images-dir", required=True, help="图片目录路径")
    parser.add_argument("--output-dir", required=True, help="分析结果输出目录路径")
    parser.add_argument("--prompts", default=None, help="可选提示词组合，多个用逗号分隔（可选）")
    parser.add_argument("--temp-prompt", default=None, help="临时提示词内容（可选）")
    parser.add_argument("--project-root", default=None, help="项目根目录路径（可选，默认为脚本所在目录）")

    args = parser.parse_args()

    # 确定项目根目录
    if args.project_root:
        project_root = os.path.abspath(args.project_root)
    else:
        project_root = os.path.dirname(os.path.abspath(__file__))

    # 添加项目根目录到sys.path，以便导入其他模块
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from config_manager import ConfigManager
    from prompt_manager import PromptManager
    from api_client import APIClient

    print("=" * 60)
    print("分析处理工具")
    print("=" * 60)
    print(f"图片目录: {args.images_dir}")
    print(f"输出目录: {args.output_dir}")
    if args.prompts:
        print(f"可选提示词: {args.prompts}")
    if args.temp_prompt:
        print(f"临时提示词: {args.temp_prompt}")
    print("=" * 60)

    # 初始化配置管理器
    try:
        config_manager = ConfigManager(project_root)
    except Exception as e:
        print(f"错误: 初始化配置管理器失败: {e}")
        return 1

    # 初始化API客户端
    try:
        auth_config = config_manager.load_auth_config()
        api_client = APIClient(
            base_url=auth_config["base_url"],
            api_key=auth_config["api_key"]
        )
        print("\nAPI客户端初始化成功")
    except Exception as e:
        print(f"错误: 初始化API客户端失败: {e}")
        return 1

    # 初始化提示词管理器
    prompt_manager = PromptManager(project_root, config_manager)
    print("提示词管理器初始化成功")

    # 解析可选提示词
    optional_prompts = []
    if args.prompts:
        optional_prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
        # 验证提示词名称
        for name in optional_prompts:
            if not config_manager.validate_prompt_name(name):
                available = config_manager.get_available_prompts()
                print(f"错误: 无效的可选提示词名称: {name}")
                print(f"可用的可选提示词: {', '.join(available)}")
                return 1

    # 创建分析处理器并运行
    processor = AnalysisProcessor(api_client, prompt_manager)
    if processor.process_images(args.images_dir, args.output_dir, optional_prompts, args.temp_prompt):
        print("\n" + "=" * 60)
        print("分析处理完成！")
        print("=" * 60)
        return 0
    else:
        print("\n错误: 分析处理失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
