@echo off
chcp 65001 >nul 2>&1
title دستیار — بررسی سلامت
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
if exist "%APPDIR%\runtime\python.exe" (
  "%APPDIR%\runtime\python.exe" -m dastyar doctor
) else (
  python -m dastyar doctor
)
echo.
pause
