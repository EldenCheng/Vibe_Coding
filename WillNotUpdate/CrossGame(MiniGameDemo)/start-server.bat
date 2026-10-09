@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Crossword Game Server
echo ========================================
echo.

call py -m http.server 8001

timeout /t 2 /nobreak >nul

start http://localhost:8001/start.html

echo Server started: http://localhost:8001
echo Close this window to stop the server.
echo.