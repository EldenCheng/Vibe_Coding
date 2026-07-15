"""
测试用例生成模块

负责从分析结果（markdown文件）生成test case JSON
支持独立运行和被main.py调用两种方式
"""

import os
import sys
import json
import re
import argparse

# 解决 Windows 控制台中文打印乱码问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


class TestCaseGenerator:
    """测试用例生成器"""

    def __init__(self, api_client, prompt_manager):
        """
        初始化测试用例生成器

        :param api_client: API客户端实例
        :param prompt_manager: 提示词管理器实例
        """
        self.api_client = api_client
        self.prompt_manager = prompt_manager

    def _clean_json_response(self, raw_content):
        """
        清理API返回的内容，提取JSON数据
        处理LLM常见的JSON格式问题

        :param raw_content: API返回的原始内容
        :return: 清理后的JSON字符串
        """
        cleaned = raw_content.strip()

        # 1. 移除Markdown代码块标记
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json", 1)[1].split("```")[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```", 1)[1].split("```")[0].strip()

        # 2. 提取JSON内容（支持数组和对象）
        # 先尝试提取对象
        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        # 再尝试提取数组
        first_bracket = cleaned.find('[')
        last_bracket = cleaned.rfind(']')

        # 根据最先出现的结构类型提取
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            if first_bracket == -1 or first_brace < first_bracket:
                cleaned = cleaned[first_brace:last_brace + 1]
            elif first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
                cleaned = cleaned[first_bracket:last_bracket + 1]
        elif first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            cleaned = cleaned[first_bracket:last_bracket + 1]

        # 3. 移除JSON中的注释
        cleaned = re.sub(r'//[^\n]*', '', cleaned)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)

        # 4. 处理单引号问题
        cleaned = re.sub(r"(?<=[{,\n])\s*'([^']*?)'\s*:", r'"\1":', cleaned)
        cleaned = re.sub(r":\s*'([^']*?)'", r': "\1"', cleaned)

        # 5. 移除尾部逗号
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

        # 6. 移除控制字符
        cleaned = re.sub(r'[\x00-\x1f\x7f]', '', cleaned)

        return cleaned

    def _load_existing_json(self, json_path):
        """
        加载已有的JSON文件（如果存在）

        :param json_path: JSON文件路径
        :return: 已有的JSON数据，文件不存在则返回空字典
        """
        if not os.path.exists(json_path):
            return {}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            return {}

    def _merge_test_cases(self, existing_data, new_data, page_name):
        """
        将新生成的test case合并到已有数据中

        支持两种格式：
        1. 对象格式：{"summary": {...}, "modes_data": {...}}
        2. 数组格式：[{"Test ID": "...", ...}, ...]

        :param existing_data: 已有的JSON数据
        :param new_data: 新生成的JSON数据
        :param page_name: 页面名称
        :return: 合并后的数据
        """
        # 如果existing_data为空，直接返回new_data
        if not existing_data:
            return new_data

        # 数组格式：直接追加
        if isinstance(new_data, list):
            if isinstance(existing_data, list):
                existing_data.extend(new_data)
            else:
                # existing_data是对象格式，new_data是数组格式
                # 将数组转换为对象格式
                if "modes_data" not in existing_data:
                    existing_data["modes_data"] = {}
                if page_name not in existing_data["modes_data"]:
                    existing_data["modes_data"][page_name] = []
                existing_data["modes_data"][page_name].extend(new_data)
            return existing_data

        # 对象格式：原有逻辑
        # 合并summary中的modes
        if "summary" in new_data and "modes" in new_data["summary"]:
            existing_modes = existing_data.get("summary", {}).get("modes", [])
            new_modes = new_data["summary"]["modes"]

            for new_mode in new_modes:
                found = False
                for existing_mode in existing_modes:
                    if existing_mode.get("mode_name") == new_mode.get("mode_name"):
                        existing_mode["total"] = existing_mode.get("total", 0) + new_mode.get("total", 0)
                        found = True
                        break
                if not found:
                    existing_modes.append(new_mode)

            existing_data.setdefault("summary", {})["modes"] = existing_modes

        # 合并modes_data
        if "modes_data" in new_data:
            existing_modes_data = existing_data.get("modes_data", {})
            for mode_name, cases in new_data["modes_data"].items():
                if mode_name in existing_modes_data:
                    existing_modes_data[mode_name].extend(cases)
                else:
                    existing_modes_data[mode_name] = cases
            existing_data["modes_data"] = existing_modes_data

        return existing_data

    def generate_test_cases(self, analysis_dir, output_json_path):
        """
        从分析结果生成test case JSON

        逐个读取analysis目录中的markdown文件，调API生成test case，
        合并后保存到同一个JSON文件中

        :param analysis_dir: 分析结果目录（如output/analysis/）
        :param output_json_path: 输出的JSON文件路径
        :return: 是否生成成功
        """
        # 检查analysis目录是否存在
        if not os.path.exists(analysis_dir):
            print(f"错误: 分析结果目录不存在: {analysis_dir}")
            return False

        # 获取所有markdown文件（按文件名排序）
        md_files = sorted([
            f for f in os.listdir(analysis_dir)
            if f.lower().endswith(".md")
        ])

        if not md_files:
            print(f"错误: 在目录 {analysis_dir} 中未找到markdown文件")
            return False

        # 读取基础生成提示词
        base_prompt = self.prompt_manager.build_generation_prompt()

        # 加载已有的JSON数据（用于追加模式）
        all_data = self._load_existing_json(output_json_path)

        total_files = len(md_files)
        success_count = 0
        fail_count = 0

        print(f"开始生成测试用例，共 {total_files} 个分析文件")

        for i, md_filename in enumerate(md_files, 1):
            md_path = os.path.join(analysis_dir, md_filename)
            page_name = os.path.splitext(md_filename)[0]

            print(f"\n[{i}/{total_files}] 正在处理: {md_filename}")

            # 读取分析结果
            with open(md_path, "r", encoding="utf-8") as f:
                analysis_content = f.read()

            # 拼接提示词：分析结果在前，基础提示词在后，附加mode分组JSON格式指令
            full_prompt = f"""{analysis_content}

{base_prompt}

Respond ONLY with a JSON object. No explanation, no markdown. Format:
{{"modes_data": {{"Mode Name": [{{"Test ID":"TC_01","Test Description":"...","Expected Result":"...","Results":"","Comment":"","Internal Bug ID":"","External Bug ID":""}}]}}}}"""

            # 调用API生成test case
            result = self.api_client.analyze_text(full_prompt)

            if result:
                try:
                    # 清理并解析JSON
                    cleaned_result = self._clean_json_response(result)
                    page_data = json.loads(cleaned_result)

                    # 合并到总数据中
                    all_data = self._merge_test_cases(all_data, page_data, page_name)
                    print(f"成功生成: {md_filename}")
                    success_count += 1

                except json.JSONDecodeError as e:
                    print(f"警告: {md_filename} 的API返回内容不是有效的JSON: {e}")
                    print(f"原始响应前200字符: {result[:200]}...")
                    fail_count += 1
            else:
                print(f"警告: {md_filename} API调用失败，跳过该文件")
                fail_count += 1

        # 保存合并后的JSON文件
        if all_data:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_json_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=2, ensure_ascii=False)

            print(f"\n测试用例生成完成: 成功 {success_count} 个，失败 {fail_count} 个")
            print(f"已保存到: {output_json_path}")
            return True
        else:
            print("\n错误: 没有成功生成任何测试用例")
            return False


def main():
    """独立运行入口"""
    parser = argparse.ArgumentParser(description="测试用例生成工具 - 从分析结果生成test case JSON")
    parser.add_argument("--analysis-dir", required=True, help="分析结果目录路径")
    parser.add_argument("--output", required=True, help="输出的JSON文件路径")
    parser.add_argument("--auth-config", default=None, help="auth.json配置文件路径（可选）")
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
    print("测试用例生成工具")
    print("=" * 60)
    print(f"分析结果目录: {args.analysis_dir}")
    print(f"输出JSON文件: {args.output}")
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

    # 创建测试用例生成器并运行
    generator = TestCaseGenerator(api_client, prompt_manager)
    if generator.generate_test_cases(args.analysis_dir, args.output):
        print("\n" + "=" * 60)
        print("测试用例生成完成！")
        print("=" * 60)
        return 0
    else:
        print("\n错误: 测试用例生成失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
