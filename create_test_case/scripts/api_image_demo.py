import base64
from openai import OpenAI

# 1. 初始化客户端，指向你本地的 vLLM 服务器
# 地址和端口与你 opencode 配置中的 baseURL 保持一致
client = OpenAI(
    api_key="EMPTY",  # 本地部署通常不需要 key，写 EMPTY 即可
    base_url="http://192.168.1.3:8080/v1" 
)

# 2. 定义一个函数，把本地图片转换为 Base64 编码
def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# 3. 准备你的图片路径和你想问的问题
image_path = "your_photo.jpg"  # 👈 替换成你本地的图片路径
prompt_text = "这是项目flowchart的图片，请帮我分析一下这个流程图, 记录它所有的逻辑, 判断, 步骤与内容, 特别是每一步对应播放的sound, animation, action或者特别的检查点。生成对应的logical structure文档。并记录为一个Json格式的文件, 我将使用它来生成test case"

try:
    # 转换图片
    base64_image = encode_image_to_base64(image_path)
    
    # 4. 发起多模态对话请求
    response = client.chat.completions.create(
        model="gemma-4-local",  # 👈 保持和你配置中的 model 名称一致
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": prompt_text
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            # 格式必须为 data:image/jpeg;base64, 后面接 Base64 字符串
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        max_tokens=512,  # 限制生成长度
        temperature=0.7
    )

    # 5. 打印大模型的回答
    print("Gemma4 的回答：")
    print(response.choices[0].message.content)

except Exception as e:
    print(f"调用失败，错误信息: {e}")