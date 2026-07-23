# Agnes Image 2.1 Flash - Python 图片生成脚本

## 简介

本项目提供 Python 脚本用于调用 Agnes Image 2.1 Flash API 生成高质量图片,支持文生图功能,生成的图片自动保存到本地目录。

## 快速开始

### 环境准备

```bash
pip install requests
```

### 设置 API Key

```powershell
$env:AGNES_API_KEY='你的API_KEY'
```

### 基本用法

```powershell
py generate_image.py --prompt "一只可爱的猫咪在草地上玩耍"
```

生成结果保存在 `images/` 目录下,文件名格式为时间戳。

## 详细用法

### 命令行参数

| 参数       | 必填 | 默认值 | 说明                       |
| ---------- | ---- | ------ | -------------------------- |
| `--prompt` | 是   | -      | 图片生成的文本描述         |
| `--size`   | 否   | 1K     | 输出尺寸 (1K/2K/3K/4K)    |
| `--ratio`  | 否   | 1:1    | 宽高比 (1:1/16:9/9:16等)  |
| `--output` | 否   | images | 自定义输出目录             |

### 常用示例

**生成 1K 正方形图片:**
```powershell
py generate_image.py --prompt "A glowing tree in a dark forest" --size 1K --ratio 1:1
```

**生成 2K 横版壁纸:**
```powershell
py generate_image.py --prompt "A sunset over the ocean" --size 2K --ratio 16:9
```

**生成竖版海报:**
```powershell
py generate_image.py --prompt "赛博朋克风格的城市街道" --size 2K --ratio 9:16
```

**自定义输出目录:**
```powershell
py generate_image.py --prompt "风景图片" --output ./my_images
```

## API 信息

- **模型名称:** `agnes-image-2.1-flash`
- **端点:** `POST https://apihub.agnes-ai.com/v1/images/generations`
- **文档:** [Agnes Image 2.1 Flash](https://agnes-ai.com/zh-Hans/docs/agnes-image-21-flash)

## 集成到项目

如需在其他项目中集成,可以直接导入模块:

```python
from generate_image import generate_image, download_image
```

调用流程:
1. `generate_image(prompt, size="1K", ratio="1:1")` → 获取图片URL
2. `download_image(image_url, save_dir)` → 保存图片到本地

## 错误处理

脚本会自动处理以下常见错误:
- 未设置 API Key
- 不支持的尺寸或宽高比
- API 请求失败
- 图片下载超时

错误信息会直接输出到控制台并终止程序。

## 版本变更记录

见 `版本变更.md`
