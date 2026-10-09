"""在操作系统的文件管理器中打开目录 / 文件（v0.2.0）。

只对「后端本机」有意义：前端浏览器可能在另一台机器上（典型：Mac 跑后端、
Windows 浏览器控制），所以前端必须自己判断前后端是否同一 OS 才显示按钮。
本模块只负责调用，路径的可信性校验由 app.py 负责。
"""
import os
import subprocess
import sys
from pathlib import Path


def supported():
    """后端是否支持打开本机文件管理器。"""
    return (os.name == "nt" or sys.platform == "darwin"
            or sys.platform.startswith("linux"))


def opener_name():
    """使用的命令名，仅用于回显给前端。"""
    if os.name == "nt":
        return "explorer"
    if sys.platform == "darwin":
        return "open"
    return "xdg-open"


def open_path(path, select=False):
    """在文件管理器中打开路径（目录则打开本身，文件则打开所在目录）。

    select=True 时尽量高亮定位到该文件/文件夹本身（Windows `explorer /select,`、
    macOS `open -R`）。返回 (是否成功, 说明文本)。
    """
    if not supported():
        return False, f"当前平台不支持打开文件管理器（{sys.platform}）"

    p = Path(path)
    if not p.exists():
        return False, f"路径不存在: {path}"

    target = p if p.is_dir() else p.parent
    try:
        if os.name == "nt":
            _win_open(p, select)
        elif sys.platform == "darwin":
            args = ["open", "-R", str(p)] if select else ["open", str(target)]
            subprocess.Popen(args)
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        return False, f"无法启动文件管理器: {exc}"
    return True, f"已在文件管理器中打开: {target}"


def _win_open(p, select):
    """Windows：目录直接打开（最稳）；文件用 explorer /select 高亮。

    踩坑（用户实测打开按钮跑去了「文档」）：
      `subprocess.Popen(["explorer", "/select," + path])` 会被 subprocess 把整个参数
      再包一层引号，命令行变成 `explorer "/select,路径"`，explorer 解析失败后
      **回退到「用户 → 文档」目录**。
    因此这里用 ShellExecuteW，把 `/select,"路径"` 原样作为参数传给 explorer，
    引号不会被改动。
    目录则直接 os.startfile（用户要的就是“打开这个目录”，比在父目录里高亮更直观，
    也避开对目录使用 /select 的同样问题）。
    """
    if p.is_dir():
        os.startfile(str(p))
        return
    if select:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "open", "explorer.exe", f'/select,"{p}"', None, 1)
        # ShellExecuteW 返回值 > 32 才算成功
        if rc <= 32:
            raise OSError(f"ShellExecuteW 调用 explorer 失败（返回码 {rc}）")
        return
    os.startfile(str(p.parent))
