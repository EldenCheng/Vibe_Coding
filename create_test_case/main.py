"""
主入口脚本

自动化测试用例生成工具的主入口，负责：
1. 解析命令行参数
2. 初始化所有模块
3. 协调整个处理流程
"""

import os
import sys
import argparse

from config_manager import ConfigManager
from prompt_manager import PromptManager
from api_client import APIClient
from file_processor import detect_file_type, process_file
from analysis_processor import AnalysisProcessor
from test_case_generator import TestCaseGenerator
from test_matrix_generator import TestMatrixGenerator


def get_project_root():
    """获取项目根目录（脚本所在目录）"""
    return os.path.dirname(os.path.abspath(__file__))


def validate_input_file(file_path):
    """
    验证输入文件

    :param file_path: 输入文件路径
    :return: 是否有效
    """
    if not os.path.exists(file_path):
        print(f"错误: 输入文件不存在: {file_path}")
        return False

    file_type = detect_file_type(file_path)
    if file_type == "unsupported":
        print(f"错误: 不支持的文件类型")
        print(f"支持的文件格式: .pdf, .jpg, .jpeg, .png, .bmp, .gif")
        return False

    return True


def validate_prompts(prompts_str, config_manager):
    """
    验证可选提示词参数

    :param prompts_str: 提示词字符串（逗号分隔）
    :param config_manager: 配置管理器实例
    :return: 有效的提示词列表，验证失败返回None
    """
    if not prompts_str:
        return []

    # 分割提示词名称
    prompt_names = [p.strip() for p in prompts_str.split(",") if p.strip()]

    # 验证每个提示词名称
    available_prompts = config_manager.get_available_prompts()
    for name in prompt_names:
        if not config_manager.validate_prompt_name(name):
            print(f"错误: 无效的可选提示词名称: {name}")
            print(f"可用的可选提示词: {', '.join(available_prompts)}")
            return None

    return prompt_names


def build_help_message(config_manager):
    """
    构建帮助信息

    :param config_manager: 配置管理器实例
    :return: 帮助信息字符串
    """
    available_prompts = config_manager.get_available_prompts()

    help_text = """自动化测试用例生成工具

使用方法:
  py main.py --input <输入文件路径> [--prompts <可选提示词>] [--temp-prompt <临时提示词>]

参数说明:
  -i, --input FILE        输入文件路径（PDF或图片）[必需]
  -p, --prompts PROMPTS   可选提示词组合，多个用逗号分隔 [可选]
  --temp-prompt TEXT      临时提示词内容 [可选]
  -h, --help              显示此帮助信息"""

    if available_prompts:
        help_text += f"\n\n可用的可选提示词:\n"
        for prompt_name in available_prompts:
            help_text += f"  - {prompt_name}\n"
    else:
        help_text += "\n\n当前没有可用的可选提示词\n"

    help_text += """
示例:
  py main.py --input Flowchart.pdf
  py main.py --input Flowchart.pdf --prompts Flowchart
  py main.py --input Flowchart.pdf --prompts Flowchart --temp-prompt "特殊分析要求"
"""

    return help_text


def main():
    """主函数"""
    # 解决 Windows 控制台中文打印乱码问题
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    # 获取项目根目录
    project_root = get_project_root()

    # 初始化配置管理器
    try:
        config_manager = ConfigManager(project_root)
    except Exception as e:
        print(f"错误: 初始化配置管理器失败: {e}")
        return 1

    # 构建自定义帮助信息
    parser = argparse.ArgumentParser(
        description="自动化测试用例生成工具",
        add_help=False  # 禁用默认的帮助参数
    )
    parser.add_argument("-h", "--help", action="store_true", help="显示帮助信息")
    parser.add_argument("-i", "--input", help="输入文件路径（PDF或图片）")
    parser.add_argument("-p", "--prompts", help="可选提示词组合，多个用逗号分隔")
    parser.add_argument("--temp-prompt", help="临时提示词内容")

    args = parser.parse_args()

    # 处理帮助参数
    if args.help:
        print(build_help_message(config_manager))
        return 0

    # 验证必需参数
    if not args.input:
        print("错误: 请指定输入文件路径")
        print("使用 -h 参数查看帮助信息")
        return 1

    # 验证输入文件
    if not validate_input_file(args.input):
        return 1

    # 验证可选提示词
    optional_prompts = []
    if args.prompts:
        optional_prompts = validate_prompts(args.prompts, config_manager)
        if optional_prompts is None:
            return 1

    # 获取输入文件的绝对路径和目录
    input_file = os.path.abspath(args.input)
    input_dir = os.path.dirname(input_file)
    input_filename = os.path.basename(input_file)
    input_name = os.path.splitext(input_filename)[0]

    # 确定输出目录
    output_base = os.path.join(input_dir, "output")
    images_dir = os.path.join(output_base, "images")
    analysis_dir = os.path.join(output_base, "analysis")
    test_cases_json_path = os.path.join(output_base, "test_cases.json")

    print("=" * 60)
    print("自动化测试用例生成工具 v1.0")
    print("=" * 60)
    print(f"输入文件: {input_file}")
    print(f"输出目录: {output_base}")
    if optional_prompts:
        print(f"可选提示词: {', '.join(optional_prompts)}")
    if args.temp_prompt:
        print(f"临时提示词: {args.temp_prompt}")
    print("=" * 60)

    # 初始化API客户端
    try:
        auth_config = config_manager.load_auth_config()
        api_client = APIClient(
            base_url=auth_config["base_url"],
            api_key=auth_config["api_key"]
        )
        print("\n[1/5] API客户端初始化成功")
    except Exception as e:
        print(f"\n错误: 初始化API客户端失败: {e}")
        return 1

    # 初始化提示词管理器
    prompt_manager = PromptManager(project_root, config_manager)
    print("[2/5] 提示词管理器初始化成功")

    # 步骤1：处理文件（PDF转图片或复制图片）
    print("\n--- 步骤1: 处理输入文件 ---")
    if not process_file(input_file, images_dir):
        print("错误: 文件处理失败")
        return 1
    print("[3/5] 文件处理完成")

    # 步骤2：分析处理（图片→markdown）
    print("\n--- 步骤2: 分析处理图片 ---")
    analysis_processor = AnalysisProcessor(api_client, prompt_manager)
    if not analysis_processor.process_images(images_dir, analysis_dir, optional_prompts, args.temp_prompt):
        print("警告: 部分图片分析失败，继续处理...")
    print("[4/5] 分析处理完成")

    # 步骤3：生成test case（预留接口，当前版本跳过）
    print("\n--- 步骤3: 生成测试用例 ---")
    test_case_generator = TestCaseGenerator(api_client, prompt_manager)
    test_case_generator.generate_test_cases(analysis_dir, test_cases_json_path)
    print("[5/5] 测试用例生成完成")

    # 步骤4：生成test matrix
    print("\n--- 步骤4: 生成测试矩阵 ---")
    test_matrix_generator = TestMatrixGenerator()
    result_path = test_matrix_generator.generate_excel(test_cases_json_path, output_base)

    if result_path:
        print("\n" + "=" * 60)
        print("所有流程已完成！")
        print(f"测试矩阵已生成: {result_path}")
        print("=" * 60)
        return 0
    else:
        print("\n错误: 测试矩阵生成失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
