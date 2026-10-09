import os
from openai import OpenAI

# 1. 初始化本地 vLLM 客户端
client = OpenAI(
    api_key="EMPTY",
    base_url="http://192.168.1.3:8080/v1"
)

# 2. 定义读取 Markdown 文件的函数
def read_markdown_file(file_path):
    # 使用 utf-8 编码读取文件，防止中文乱码
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

# 3. 设置你本地的 .md 文件路径和需求说明
md_file_path = "document_analysis.md"  # 👈 替换为你保存的 md 文件路径
user_requirement = "请仔细阅读以下文档/表格内容，并帮我梳理其核心大意，提取出关键的数据和指标，最后生成一份分析报告。"

if not os.path.exists(md_file_path):
    print(f"❌ 错误：未找到文件 '{md_file_path}'，请检查文件路径是否正确。")
else:
    try:
        # 读取 md 文件内容
        print(f"正在读取文件: {md_file_path} ...")
        markdown_content = read_markdown_file(md_file_path)
        
        # 4. 组装 Prompt 提示词
        # 将用户的任务要求和 md 文件内容拼接在一起
        full_prompt = f"{user_requirement}\n\n---\n以下是文档内容：\n\n{markdown_content}"
        
        print("正在向本地 Gemma4 发送 API 请求...")
        
        # 5. 发起对话请求（纯文本请求）
        response = client.chat.completions.create(
            model="gemma-4-local",
            messages=[
                {
                    "role": "user",
                    "content": full_prompt
                }
            ],
            # 💡 核心设置：根据你 md 文件的长度，设置合理的返回 Token 限制
            # 文本生成的 max_tokens 相比于多模态非常省显存，可以放心设大
            max_tokens=4096,  
            temperature=0.3,   # 较低的随机性可以使分析和提取数据更严谨、准确
            timeout=300.0      # 设置超时等待时间为 5 分钟，防止长文本处理时超时
        )
        
        # 6. 打印 Gemma4 的分析输出
        print("\n--- ✨ Gemma4 的分析报告 ---")
        print(response.choices[0].message.content)

    except Exception as e:
        print(f"\n❌ 运行失败，错误原因: {e}")