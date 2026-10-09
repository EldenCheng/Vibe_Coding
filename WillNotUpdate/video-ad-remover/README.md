# 视频广告移除工具

自动检测并移除视频中的广告片段,支持MP4和TS格式。

## 快速开始

```bash
# 处理单个视频
python remove_ad.py "视频文件.mp4"

# 批量处理
python remove_ad.py "*.mp4"

# 使用GPU加速
python remove_ad.py "*.mp4" -g
```

## 功能特点

- ✅ 自动检测广告(基于PTS时间戳跳跃)
- ✅ 快速复制处理,不重新编码
- ✅ 支持NVIDIA GPU加速(NVENC)
- ✅ 支持批量处理和通配符匹配
- ✅ 支持MP4和TS格式

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `files` | 视频文件或通配符 | 必需 |
| `-d, --duration` | 广告最大时长(秒) | 30 |
| `-o, --output-dir` | 输出目录 | 与源文件相同 |
| `-g, --gpu` | 使用GPU加速 | False |

## 使用示例

```bash
# 基本使用
python remove_ad.py "牙狼01.mp4"

# 指定广告时长
python remove_ad.py "*.mp4" -d 25

# 指定输出目录
python remove_ad.py "*.mp4" -o "cleaned/"

# 使用GPU加速
python remove_ad.py "*.mp4" -g

# 组合使用
python remove_ad.py "牙狼*.mp4" -d 30 -o "cleaned/" -g
```

## 输出文件

- 输入: `视频文件.mp4`
- 输出: `视频文件_clean.mp4`

## 依赖要求

- Python 3.x
- FFmpeg (需要在系统PATH中)
- FFprobe (需要在系统PATH中)
- NVIDIA显卡驱动(如果使用GPU加速)

## 文档

- [项目设计文档.md](项目设计文档.md) - 详细的设计思路和技术实现
- [版本变更.md](版本变更.md) - 版本历史和更新日志

## 工作原理

1. 使用ffprobe获取视频的PTS(显示时间戳)值
2. 检测PTS中的最大跳跃(不连续点)
3. 在跳跃点之前移除广告内容
4. 使用ffmpeg将两段视频拼接成完整文件

## 注意事项

- 广告检测基于PTS时间戳跳跃,适用于被篡改的视频文件
- 如果视频没有检测到广告跳跃,会自动跳过
- 处理后的视频会保持原始质量(CPU模式)
- GPU模式需要NVIDIA显卡和支持

## 许可证

个人工具,无特定许可证。
