@echo off
chcp 65001 >nul 2>&1
setlocal
title دستیار
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
cd /d "%APPDIR%"
if exist "%APPDIR%\runtime\python.exe" (
  "%APPDIR%\runtime\python.exe" -m dastyar run %*
  exit /b %errorlevel%
)
where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Run install.cmd first.
  pause
  exit /b 1
)
python -m dastyar run %*
