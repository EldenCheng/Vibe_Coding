# 场景生成器帮助文档

## 概述

`generate_demo_scene.py` 是一个Python脚本，用于从测试资源生成符合Chat With Me应用格式的场景数据。

## 功能

- 解析文本格式的问题文件
- 生成符合设计文档规范的JSON元数据
- 复制图片资源到指定目录
- 创建或更新场景索引文件

## 使用方法

### 基本用法

```bash
cd scripts
python generate_demo_scene.py
```

### 自定义生成

如果你需要生成不同的场景，可以修改脚本中的配置参数：

```python
# 在main()函数中修改以下配置
source_dir = "../resources/your_folder"      # 源资源目录
output_dir = "../demo/assets/scenes"         # 输出目录
scene_id = "junior_market"                    # 场景ID
grade_level = "junior"                        # 年级: primary/junior/senior
```

## 文件要求

### 源目录结构

```
resources/test_sc01/
├── Market.jpg           # 场景图片
└── questions.txt        # 问题文件
```

### questions.txt 格式

问题文件使用以下格式：

```
第一个问题:
What fruits can you see in the market? Name at least three kinds of fruits.

第二个问题:
What are the students doing right now?

第三个问题:
Imagine you are a vendor. How would you describe your fresh oranges?
```

**格式要求：**
- 每个问题以"第N个问题:"开头
- 问题文本紧随冒号之后
- 问题之间用空行分隔
- 支持中英文混合

## 输出结果

脚本会生成以下文件结构：

```
demo/assets/scenes/
├── index.json                           # 场景索引
└── junior_market/                        # 场景文件夹
    ├── meta.json                        # 场景元数据
    ├── image.jpg                        # 复制的图片
    └── questions.json                   # 问题列表（JSON格式）
```

### index.json

```json
{
  "scenes": [
    "junior_market"
  ]
}
```

### meta.json

```json
{
  "id": "junior_market",
  "title": "A Visit to the Street Market",
  "gradeLevel": "junior",
  "imageAlt": "A busy street market with vendors selling fresh fruits",
  "imageDescription": "A bustling street market scene...",
  "createdAt": "2024-07-24"
}
```

### questions.json

```json
{
  "questions": [
    {
      "id": "q1",
      "text": "What fruits can you see in the market? Name at least three kinds of fruits.",
      "order": 1
    }
  ]
}
```

## 场景ID命名规则

场景ID必须遵循以下格式：

```
{gradeLevel}_{描述性名称}
```

**示例：**
- `primary_zoo` - 小学年级，动物园场景
- `junior_market` - 初中年级，市场场景
- `senior_climate` - 高中年级，气候场景

**要求：**
- 全部小写
- 空格用下划线替代
- gradeLevel 必须是 `primary`、`junior` 或 `senior`

## 故障排除

### 场景目录已存在

如果目标场景目录已存在，脚本会报错。你可以：

1. 删除现有目录后重新运行
2. 在代码中设置 `overwrite=True`

```python
generator.generate_scene(
    # ... 其他参数
    overwrite=True  # 覆盖现有场景
)
```

### 问题文件格式错误

如果问题文件格式不符合要求，脚本会无法解析。请检查：

- 是否使用"第N个问题:"格式
- 冒号后是否有问题文本
- 问题之间是否有空行分隔

### 图片文件未找到

确保图片文件存在于源目录中，并且文件名正确。

## 高级用法

### 生成多个场景

你可以创建多个源目录，分别生成不同场景：

```python
# 示例：生成多个场景
scenes = [
    ("../resources/test_sc01", "junior_market", "junior"),
    ("../resources/test_sc02", "primary_zoo", "primary"),
]

for source, scene_id, grade in scenes:
    generator = SceneGenerator(source, "../demo/assets/scenes", scene_id, grade)
    generator.generate_scene(
        questions_file="questions.txt",
        image_file="scene.jpg"
    )
```

### 自定义元数据

你可以自定义场景的元数据：

```python
generator.generate_scene(
    # ...
    title="自定义标题",
    image_alt="自定义图片描述",
    image_description="详细的图片描述，用于AI评分"
)
```

## 注意事项

1. **图片格式**：脚本会自动复制图片，不会修改格式或大小
2. **编码问题**：问题文件应使用UTF-8编码
3. **目录权限**：确保脚本有权限创建目录和复制文件
4. **ID一致性**：场景ID应该与文件夹名保持一致

## 支持与反馈

如遇到问题或需要新功能，请联系开发团队。