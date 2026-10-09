"""启动脚本用的 Python 解释器选择器。

背景（本机实测）：默认的 `py` 可能是 **free-threading 构建**（如 Python 3.14t），
而 Playwright 的**同步 API** 在该构建上 `sync_playwright().start()` 会直接段错误，
视频下载器的嗅探 / 批量 / 播放三种模式都依赖它。

让 Python 选择逻辑只有一份：这里直接复用 `backend/config.py` 的 `resolve_python()`，
并把选中的解释器路径打到 stdout（只打这一行，供 start_server.bat 的 for /f 读取）。
诊断信息一律走 stderr。这样「管理器自身」也跑在 GIL 构建上，
自动改选就从「兜底」变成「主路径」，行为更可预测。

用法（在 download-manager 目录下）：
    py -X utf8 pick_python.py
"""
import sys
from pathlib import Path

# 允许从任意 cwd 运行：把本文件所在目录（download-manager）加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_config, resolve_python  # noqa: E402


def main():
    try:
        cfg = get_config()
        py, reason = resolve_python(cfg)
    except Exception as exc:  # 配置损坏等：不要让启动脚本半途而废，回退即可
        print(f"[错误] 解释器选择失败，将由启动脚本回退到 py: {exc}", file=sys.stderr)
        return 1
    if not py:
        print(f"[错误] {reason}", file=sys.stderr)
        return 1
    print(f"[启动] 选用解释器: {py}（{reason}）", file=sys.stderr)
    print(py)  # 唯一一行 stdout，供 for /f 捕获
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
