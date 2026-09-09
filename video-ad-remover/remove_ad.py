import subprocess
import sys
import os
import glob
import argparse

def get_pts_values(video_file):
    """使用ffprobe获取视频的PTS值"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'packet=pts_time',
        '-of', 'csv=p=0',
        video_file
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    pts_values = []
    for line in result.stdout.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith('['):
            try:
                pts_values.append(float(line))
            except ValueError:
                continue
    return pts_values

def find_discontinuity(pts_values, min_jump=5.0):
    """找到PTS中的最大跳跃(不连续点)"""
    if len(pts_values) < 2:
        return None, None
    
    max_jump = 0
    max_jump_index = 0
    
    for i in range(1, len(pts_values)):
        jump = pts_values[i] - pts_values[i-1]
        if jump > max_jump:
            max_jump = jump
            max_jump_index = i
    
    if max_jump < min_jump:
        return None, None
    
    return pts_values[max_jump_index - 1], max_jump

def get_video_duration(video_file):
    """获取视频总时长"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0',
        video_file
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return None

def remove_ad(video_file, output_file, ad_duration=30, use_gpu=False):
    """移除视频中的广告"""
    print(f"处理: {os.path.basename(video_file)}")
    
    # 获取PTS值
    pts_values = get_pts_values(video_file)
    if not pts_values:
        print("  错误: 无法获取PTS值")
        return False
    
    # 找到不连续点
    discontinuity, jump_size = find_discontinuity(pts_values)
    if discontinuity is None:
        print("  未检测到广告跳跃，跳过")
        return False
    
    print(f"  检测到跳跃: {jump_size:.2f}秒 @ {discontinuity:.2f}秒")
    
    # 计算广告开始点(在不连续点之前)
    ad_start = max(0, discontinuity - ad_duration)
    print(f"  移除范围: {ad_start:.2f}秒 - {discontinuity:.2f}秒")
    
    # 获取视频总时长
    duration = get_video_duration(video_file)
    if duration is None:
        print("  错误: 无法获取视频时长")
        return False
    
    # 创建临时文件名
    temp1 = f"{output_file}.temp1.ts"
    temp2 = f"{output_file}.temp2.ts"
    
    # 根据GPU设置选择编码器
    if use_gpu:
        video_codec = ['-c:v', 'h264_nvenc', '-preset', 'fast', '-cq', '23']
        print("  使用GPU加速 (NVENC)")
    else:
        video_codec = ['-c', 'copy']
        print("  使用CPU (快速复制)")
    
    try:
        # 剪切第一段(广告前)
        cmd1 = [
            'ffmpeg', '-y', '-ss', '0',
            '-i', video_file,
            '-to', str(ad_start),
        ] + video_codec + [
            '-f', 'mpegts',
            temp1
        ]
        subprocess.run(cmd1, capture_output=True)
        
        # 剪切第二段(广告后)
        cmd2 = [
            'ffmpeg', '-y', '-ss', str(discontinuity),
            '-i', video_file,
        ] + video_codec + [
            '-f', 'mpegts',
            temp2
        ]
        subprocess.run(cmd2, capture_output=True)
        
        # 检查临时文件是否存在
        if not os.path.exists(temp1) or not os.path.exists(temp2):
            print("  错误: 剪切失败")
            return False
        
        # 拼接两段视频
        cmd3 = [
            'ffmpeg', '-y',
            '-i', f'concat:{temp1}|{temp2}',
        ] + video_codec + [
            '-movflags', '+faststart',
            output_file
        ]
        result = subprocess.run(cmd3, capture_output=True, text=True)
        
        if result.returncode == 0 and os.path.exists(output_file):
            print(f"  完成: {output_file}")
            return True
        else:
            print(f"  错误: 拼接失败")
            if result.stderr:
                print(f"  详情: {result.stderr[:200]}")
            return False
            
    finally:
        # 清理临时文件
        for temp in [temp1, temp2]:
            if os.path.exists(temp):
                try:
                    os.remove(temp)
                except:
                    pass

def main():
    parser = argparse.ArgumentParser(
        description='移除视频中的广告',
        usage='python remove_ad.py <视频文件或通配符> [选项]'
    )
    parser.add_argument('files', nargs='+', help='视频文件或通配符 (*.mp4, *.ts)')
    parser.add_argument('-d', '--duration', type=int, default=30,
                        help='广告最大时长(秒), 默认30秒')
    parser.add_argument('-o', '--output-dir', 
                        help='输出目录, 默认与源文件相同')
    parser.add_argument('-g', '--gpu', action='store_true',
                        help='使用NVIDIA GPU加速 (NVENC)')
    
    args = parser.parse_args()
    
    # 收集所有匹配的文件
    video_files = []
    for pattern in args.files:
        # 处理通配符
        matched = glob.glob(pattern)
        if matched:
            video_files.extend(matched)
        elif os.path.exists(pattern):
            video_files.append(pattern)
    
    if not video_files:
        print("错误: 未找到匹配的视频文件")
        sys.exit(1)
    
    print(f"找到 {len(video_files)} 个视频文件")
    if args.gpu:
        print("模式: GPU加速 (NVENC)")
    else:
        print("模式: CPU (快速复制)")
    print("-" * 50)
    
    success_count = 0
    for video_file in video_files:
        # 确定输出路径
        if args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            output_file = os.path.join(args.output_dir, 
                                       os.path.basename(video_file))
        else:
            # 在文件名后添加 _clean
            base, ext = os.path.splitext(video_file)
            output_file = f"{base}_clean{ext}"
        
        if remove_ad(video_file, output_file, args.duration, args.gpu):
            success_count += 1
    
    print("-" * 50)
    print(f"处理完成: {success_count}/{len(video_files)} 成功")

if __name__ == '__main__':
    main()
