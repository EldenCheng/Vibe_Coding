"""
配置管理模块

负责管理所有配置文件的读取和验证：
- config/auth.json: API认证信息（base_url, api_key）
- config/prompts_mapping.json: 可选提示词名称与文件路径的映射
"""

import json
import os


class ConfigManager:
    """配置管理器，负责读取和验证配置文件"""

    def __init__(self, project_root):
        """
        初始化配置管理器

        :param project_root: 项目根目录路径
        """
        self.project_root = project_root
        self.config_dir = os.path.join(project_root, "config")
        self.auth_config_path = os.path.join(self.config_dir, "auth.json")
        self.prompts_mapping_path = os.path.join(self.config_dir, "prompts_mapping.json")
        self._prompts_mapping = None

    def load_auth_config(self):
        """
        读取API认证配置

        :return: 包含base_url和api_key的字典
        :raises FileNotFoundError: 配置文件不存在
        :raises json.JSONDecodeError: 配置文件格式错误
        """
        if not os.path.exists(self.auth_config_path):
            raise FileNotFoundError(f"认证配置文件不存在: {self.auth_config_path}")

        with open(self.auth_config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 验证必要的字段
        if "base_url" not in config:
            raise KeyError("认证配置缺少base_url字段")
        if "api_key" not in config:
            raise KeyError("认证配置缺少api_key字段")

        return config

    def load_prompts_mapping(self):
        """
        读取可选提示词映射配置

        :return: 提示词映射字典，格式为 {"名称": "文件路径"}
        :raises FileNotFoundError: 配置文件不存在
        :raises json.JSONDecodeError: 配置文件格式错误
        """
        if self._prompts_mapping is not None:
            return self._prompts_mapping

        if not os.path.exists(self.prompts_mapping_path):
            raise FileNotFoundError(f"提示词映射配置文件不存在: {self.prompts_mapping_path}")

        with open(self.prompts_mapping_path, "r", encoding="utf-8") as f:
            self._prompts_mapping = json.load(f)

        return self._prompts_mapping

    def get_available_prompts(self):
        """
        获取所有可用的可选提示词名称列表

        :return: 提示词名称列表
        """
        mapping = self.load_prompts_mapping()
        return list(mapping.keys())

    def validate_prompt_name(self, name):
        """
        验证提示词名称是否有效

        :param name: 提示词名称
        :return: 是否有效
        """
        mapping = self.load_prompts_mapping()
        return name in mapping

    def get_prompt_file_path(self, name):
        """
        根据提示词名称获取对应的文件路径

        :param name: 提示词名称
        :return: 提示词文件的绝对路径
        :raises KeyError: 提示词名称不存在
        """
        mapping = self.load_prompts_mapping()
        if name not in mapping:
            raise KeyError(f"无效的提示词名称: {name}")

        # 将相对路径转换为绝对路径（相对于项目根目录）
        relative_path = mapping[name]
        return os.path.join(self.project_root, relative_path)
