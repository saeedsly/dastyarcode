@echo off
chcp 65001 >nul 2>&1
setlocal
title Dastyar
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
cd /d "%APPDIR%"
if exist "%APPDIR%\runtime\python.exe" goto :private
where python >nul 2>&1
if not errorlevel 1 goto :system
echo.
echo  Python was not found. Please run install.cmd first.
pause
exit /b 1
:private
"%APPDIR%\runtime\python.exe" -m dastyar run %*
exit /b %errorlevel%
:system
python -m dastyar run %*
