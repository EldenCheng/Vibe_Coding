"""
提示词管理模块

负责管理提示词的读取和拼接：
- 基础提示词：始终作为第一部分
- 可选提示词：通过prompts_mapping.json配置，支持单选或多选
- 临时提示词：通过命令行参数输入，作为最后一部分
"""

import os


class PromptManager:
    """提示词管理器，负责读取和拼接提示词组合"""

    def __init__(self, project_root, config_manager):
        """
        初始化提示词管理器

        :param project_root: 项目根目录路径
        :param config_manager: 配置管理器实例
        """
        self.project_root = project_root
        self.prompts_dir = os.path.join(project_root, "prompts")
        self.config_manager = config_manager

        # 基础提示词文件名
        self.base_analysis_prompt_file = "基础分析提示词.md"
        self.base_generation_prompt_file = "基础生成提示词.md"
        self.base_format_prompt_file = "基础格式提示词.md"

    def _read_prompt_file(self, file_path):
        """
        读取提示词文件内容

        :param file_path: 提示词文件路径
        :return: 提示词内容
        :raises FileNotFoundError: 文件不存在
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"提示词文件不存在: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def get_base_analysis_prompt(self):
        """
        读取基础分析提示词内容

        :return: 基础分析提示词内容
        """
        file_path = os.path.join(self.prompts_dir, self.base_analysis_prompt_file)
        return self._read_prompt_file(file_path)

    def get_base_generation_prompt(self):
        """
        读取基础生成提示词内容

        :return: 基础生成提示词内容
        """
        file_path = os.path.join(self.prompts_dir, self.base_generation_prompt_file)
        return self._read_prompt_file(file_path)

    def get_base_format_prompt(self):
        """
        读取基础格式提示词内容

        :return: 基础格式提示词内容
        """
        file_path = os.path.join(self.prompts_dir, self.base_format_prompt_file)
        return self._read_prompt_file(file_path)

    def get_optional_prompt(self, name):
        """
        根据名称读取可选提示词内容

        :param name: 提示词名称（如"Flowchart"）
        :return: 提示词内容
        :raises KeyError: 提示词名称不存在
        """
        # 通过config_manager获取提示词文件的绝对路径
        file_path = self.config_manager.get_prompt_file_path(name)
        return self._read_prompt_file(file_path)

    def build_analysis_prompt(self, optional_prompts=None, temp_prompt=None):
        """
        拼接分析提示词组合

        拼接顺序：基础分析提示词 → 可选提示词（按用户指定顺序）→ 临时提示词

        :param optional_prompts: 可选提示词名称列表，如["Flowchart", "AnotherPrompt"]
        :param temp_prompt: 临时提示词内容
        :return: 拼接后的完整提示词
        """
        parts = []

        # 1. 基础分析提示词始终作为第一部分
        parts.append(self.get_base_analysis_prompt())

        # 2. 可选提示词作为第二部分，按用户指定的顺序拼接
        if optional_prompts:
            for prompt_name in optional_prompts:
                try:
                    optional_content = self.get_optional_prompt(prompt_name)
                    parts.append(f"\n---\n\n{optional_content}")
                except KeyError:
                    # 这个错误应该在命令行参数验证时就已经捕获了
                    # 这里作为安全检查，跳过无效的提示词
                    print(f"警告: 跳过无效的可选提示词: {prompt_name}")

        # 3. 临时提示词作为最后一部分
        if temp_prompt and temp_prompt.strip():
            parts.append(f"\n---\n\n{temp_prompt}")

        return "\n".join(parts)

    def build_generation_prompt(self):
        """
        拼接生成test case提示词

        当前版本只返回基础生成提示词（预留接口）

        :return: 生成提示词内容
        """
        return self.get_base_generation_prompt()

    def build_format_prompt(self):
        """
        拼接格式提示词

        当前版本只返回基础格式提示词

        :return: 格式提示词内容
        """
        return self.get_base_format_prompt()
