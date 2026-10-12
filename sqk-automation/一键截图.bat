@echo off
chcp 65001 >nul
setlocal
rem 切到脚本所在目录，保证相对路径（config/、screen_shot/）正确
cd /d "%~dp0"

echo ==========================================
echo   电视盒子一键截图  %date% %time%
echo ==========================================
echo.

rem 想改成别的操作，直接换掉 run 后面的操作名或编号（py main.py list 查看全部）
py main.py run screenshot %*
set "RC=%errorlevel%"

echo.
if "%RC%"=="0" (
    echo 完成。截图在 screen_shot 文件夹里。
) else (
    echo 失败，退出码 %RC%，请按上面的提示排查。
)

rem 双击运行时保留窗口；命令行可用 NO_PAUSE=1 跳过
if not defined NO_PAUSE pause

exit /b %RC%
