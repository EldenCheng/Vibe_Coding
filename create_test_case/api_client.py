"""
API调用模块

封装大模型API调用，支持图片模式（多模态）和文本模式两种调用方式
"""

import base64
from openai import OpenAI


class APIClient:
    """API客户端，封装大模型API调用"""

    def __init__(self, base_url, api_key, model="gemma-4-local"):
        """
        初始化API客户端

        :param base_url: API服务器地址
        :param api_key: API密钥
        :param model: 使用的模型名称
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def _encode_image_to_base64(self, image_path):
        """
        将本地图片转换为Base64编码

        :param image_path: 图片文件路径
        :return: Base64编码字符串
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def analyze_image(self, image_path, prompt_text, max_tokens=10240, temperature=0.2, timeout=1200.0):
        """
        通过多模态API分析图片内容

        :param image_path: 图片文件路径
        :param prompt_text: 提示词内容
        :param max_tokens: 最大生成token数
        :param temperature: 生成温度
        :return: 大模型的回答文本，失败返回None
        """
        try:
            base64_image = self._encode_image_to_base64(image_path)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"调用API分析图片时出错: {e}")
            return None

    def analyze_text(self, prompt_text, max_tokens=10240, temperature=0.3, timeout=1200.0):
        """
        通过纯文本API分析内容

        :param prompt_text: 提示词内容
        :param max_tokens: 最大生成token数
        :param temperature: 生成温度
        :param timeout: 超时时间（秒）
        :return: 大模型的回答文本，失败返回None
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt_text
                    }
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"调用API分析文本时出错: {e}")
            return None
