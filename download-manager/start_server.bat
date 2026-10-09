@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  Unified Download Manager - Windows launcher
rem
rem  File encoding: UTF-8 (no BOM) + CRLF.
rem
rem  IMPORTANT: cmd.exe parses a .bat file using the local OEM
rem  codepage (cp936 on Chinese Windows), NOT UTF-8.  Multi-byte
rem  UTF-8 Chinese in a "rem" line can therefore be mis-decoded
rem  and break the batch syntax.  Rules kept here:
rem    - ALL rem comments are ASCII (English) only;
rem    - Chinese appears ONLY in "echo" lines (display text);
rem    - flow control uses "goto" labels, never "( )" blocks.
rem  If the encoding is ever mangled, at worst the text looks
rem  garbled - the script still runs.
rem ============================================================

rem Choose the Python interpreter: prefer a normal (GIL) build.
rem Rationale: the default "py" may be free-threading (3.14t), on
rem which Playwright's sync API segfaults (see pick_python.py and
rem the design doc, section 21.4.1).  Running the manager itself on a
rem GIL build makes behavior predictable.  Selection reuses
rem backend/config.py resolve_python(); an explicit
rem python.python_exe in config.json still takes precedence.
set "PYEXE="
where py >nul 2>nul && goto :pickpy
where python >nul 2>nul && set "PYEXE=python"
if defined PYEXE goto :run
goto :nopython

:pickpy
for /f "delims=" %%P in ('py -X utf8 pick_python.py') do set "PYEXE=%%P"
if not defined PYEXE set "PYEXE=py"
goto :run

:run
echo 管理器将使用: %PYEXE%
"%PYEXE%" --version
echo.
echo 正在启动统一下载管理器...
echo 按 Ctrl+C 或直接关闭本窗口即可停止服务。
echo.

"%PYEXE%" -X utf8 server.py %*
set "CODE=%ERRORLEVEL%"

echo.
echo [提示] 服务已退出, 退出码 %CODE%
echo        常见原因与处理:
echo          - 端口 8765 被占用: 改 config.json 的 server.port, 或运行 start_server.bat --port 9000
echo          - frontend 目录缺失: 检查是否完整克隆了仓库
echo.
pause
exit /b %CODE%

:nopython
echo.
echo [错误] 没有找到 Python
echo        请先安装 Python 3.9 或更高版本: https://www.python.org/downloads/
echo        安装时请勾选 "Add Python to PATH"
echo.
pause
exit /b 1
