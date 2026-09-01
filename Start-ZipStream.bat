@echo off
setlocal EnableDelayedExpansion
title ZipStream Hub - 1-Click Launcher
color 0B

echo.
echo  ==============================================================
echo            ⚡  ZipStream Hub  -  1-Click Launcher  ⚡
echo    Instant Zero-Disk Remote ZIP Streaming Engine for Windows
echo  ==============================================================
echo.

:: 1. Detect Python 3 Interpreter
set "PY_CMD="

where python >nul 2>nul
if %errorlevel% equ 0 (
    python -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>nul
    if !errorlevel! equ 0 set "PY_CMD=python"
)

if not defined PY_CMD (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py -3 -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>nul
        if !errorlevel! equ 0 set "PY_CMD=py -3"
    )
)

if not defined PY_CMD (
    where python3 >nul 2>nul
    if %errorlevel% equ 0 (
        python3 -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>nul
        if !errorlevel! equ 0 set "PY_CMD=python3"
    )
)

if not defined PY_CMD (
    echo [ERROR] Python 3 was not detected on this system!
    echo.
    echo Please install Python 3 (Python 3.9+ recommended) from:
    echo https://www.python.org/downloads/
    echo.
    echo (Make sure to check "Add Python to PATH" during installation)
    echo.
    pause
    exit /b 1
)

echo [OK] Using Python: %PY_CMD%

:: 2. Check and Install Dependencies
echo [*] Checking dependencies...
%PY_CMD% -c "import urllib3" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing required dependencies (urllib3)...
    if exist "%~dp0requirements.txt" (
        %PY_CMD% -m pip install -r "%~dp0requirements.txt"
    ) else (
        %PY_CMD% -m pip install urllib3
    )
    if %errorlevel% neq 0 (
        echo [WARNING] Dependency installation failed. Retrying with --user flag...
        %PY_CMD% -m pip install --user urllib3
    )
)
echo [OK] Dependencies verified.

:: 3. Start Control Panel / Web GUI
echo.
echo [*] Starting ZipStream Hub...
echo.

cd /d "%~dp0"
start "" %PY_CMD% control_panel.py
start http://127.0.0.1:8787/

echo ZipStream Hub started successfully. You can close this console.
timeout /t 3 >nul
exit /b 0
