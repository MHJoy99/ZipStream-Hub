@echo off
title Install ZipStream Hub Shortcut
color 0A

echo.
echo ==============================================================
echo     Creating "ZipStream Hub" Shortcut on Windows Desktop...
echo ==============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-Desktop-Shortcut.ps1"

if %errorlevel% equ 0 (
    echo.
    echo [OK] Shortcut created successfully on your Desktop!
) else (
    echo.
    echo [ERROR] Failed to create shortcut.
)

echo.
pause
