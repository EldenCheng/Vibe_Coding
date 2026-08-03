@echo off
setlocal
REM Chat With Me Demo Server Launcher
REM This script starts a simple HTTP server for the demo

echo ================================================
echo Chat With Me Demo - Server Launcher
echo ================================================
echo.

REM Detect Python (prefer py launcher, fall back to python)
set "PYTHON_CMD="
py --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.6 or higher
    pause
    exit /b 1
)

echo Python detected: %PYTHON_CMD%
echo.

REM Navigate to project root (parent of this demo directory).
REM simple_server.py serves the "demo" directory relative to the current
REM working directory, so it must be launched from the project root.
cd /d "%~dp0.."

REM Start the server
echo Starting web server...
echo.
%PYTHON_CMD% scripts\simple_server.py

REM Keep window open if server crashes
if %errorlevel% neq 0 (
    echo.
    echo Server exited with error code: %errorlevel%
    pause
)
