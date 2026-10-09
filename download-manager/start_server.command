#!/bin/bash
# ============================================================
#  统一下载管理器 —— macOS 启动脚本
#  双击运行（首次需先执行: chmod +x start_server.command）
#  服务在前台运行，关掉终端窗口即停止服务。
# ============================================================
set -u
cd "$(dirname "$0")" || exit 1

# ---- 1. 找 Python ----
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "[错误] 没有找到 Python 3。"
  echo "       请从 https://www.python.org/downloads/ 安装 Python 3.9 以上版本。"
  echo "       （本机若已装 Homebrew，也可以: brew install python3）"
  read -r -p "按回车键退出..." _
  exit 1
fi

echo "使用解释器: $PY  ($("$PY" --version 2>&1))"

# ---- 2. 版本检查（管理器要求 3.9+） ----
"$PY" - <<'PYCHECK'
import sys
if sys.version_info < (3, 9):
    print(f"[错误] 需要 Python 3.9 或更高版本，当前为 {sys.version.split()[0]}")
    sys.exit(1)
print(f"版本检查通过: {sys.version.split()[0]}")
PYCHECK
if [ $? -ne 0 ]; then
  read -r -p "按回车键退出..." _
  exit 1
fi

# ---- 3. 依赖检查 ----
# 管理器本身只用标准库，不需要任何第三方包；这里检查的是**三个下载器**的依赖，
# 且只提示、不安装（避免在别人的机器上擅自装包）。
# 清单与 backend/adapters/m3u_down.py 的 top_level_modules 保持一致。
check_module() {
  "$PY" -c "import $1" >/dev/null 2>&1
}

MISSING=""
for pkg in requests bs4 lxml; do
  check_module "$pkg" || MISSING="$MISSING $pkg"
done
if [ -n "$MISSING" ]; then
  echo
  echo "[提示] 电子书 / E-Hentai 下载器缺少依赖:$MISSING"
  echo "       安装: $PY -m pip install requests beautifulsoup4 lxml"
fi

# 视频下载器：这两个是顶层 import，缺了连「直接下载」和 --version 都跑不起来
VIDEO_MISSING=""
check_module Crypto     || VIDEO_MISSING="$VIDEO_MISSING pycryptodome(AES解密)"
check_module playwright || VIDEO_MISSING="$VIDEO_MISSING playwright(嗅探/播放器模式)"
if [ -n "$VIDEO_MISSING" ]; then
  echo
  echo "[提示] 视频下载器缺少必需依赖:$VIDEO_MISSING"
  echo "       它们是 m3u_down 的顶层依赖，缺失时连直链下载都会失败。"
  echo "       安装: $PY -m pip install pycryptodome playwright"
  echo "             $PY -m playwright install chromium"
fi
check_module socks || \
  echo "[提示] 未安装 pysocks —— 仅在使用 socks5:// 代理时需要，http 代理可忽略"

# ebooklib 只有「生成 EPUB」这一步需要
check_module ebooklib || \
  echo "[提示] 未安装 ebooklib —— 电子书可以下载，但生成 EPUB 会失败（$PY -m pip install ebooklib）"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[提示] 未找到 ffmpeg —— 视频下载器合并切片必需（brew install ffmpeg）"
fi

# yt-dlp 是惰性 import：只影响「yt-dlp 下载」方式（B站/YouTube 等），其它功能不受影响
check_module yt_dlp || \
  echo "[提示] 未安装 yt-dlp —— 仅「yt-dlp 下载」方式需要（$PY -m pip install -U yt-dlp）"
# YouTube 还需一个 JS 运行时（yt-dlp 默认用 deno，本仓库配置里已同时启用 node）
if ! command -v node >/dev/null 2>&1 && ! command -v deno >/dev/null 2>&1; then
  echo "[提示] 未找到 node/deno —— 仅 YouTube 需要（brew install node）"
fi

# ---- 4. 防休眠提示（真正的防休眠由 server.py 调 caffeinate 完成） ----
if ! command -v caffeinate >/dev/null 2>&1; then
  echo "[提示] 未找到 caffeinate，无法自动阻止系统休眠；长任务请到"
  echo "       系统设置 → 锁定屏幕 → 关闭「显示器关闭时进入睡眠」"
fi

echo
echo "正在启动统一下载管理器..."
echo "（按 Ctrl+C 停止服务；或直接关闭本窗口）"
echo

# -X utf8 保证中文与 ✓/✗ 不会因编码报错
"$PY" -X utf8 server.py "$@"
CODE=$?

echo
if [ "$CODE" -ne 0 ]; then
  echo "[提示] 服务退出，退出码 $CODE。常见原因："
  echo "       · 端口 8765 被占用 → 改 config.json 的 server.port，或 ./start_server.command --port 9000"
  echo "       · 首次运行被 macOS 防火墙拦截 → 系统设置 → 网络 → 防火墙 里允许 Python"
  echo "       · 若刚改过代码，确认 frontend/ 目录存在"
fi
read -r -p "按回车键退出..." _
exit "$CODE"
