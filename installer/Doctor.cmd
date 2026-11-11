@echo off
chcp 65001 >nul 2>&1
setlocal
title Dastyar - Doctor
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
cd /d "%APPDIR%"
if exist "%APPDIR%\runtime\python.exe" goto :private
where python >nul 2>&1
if errorlevel 1 goto :nopython
python -m dastyar.installer_ui doctor
goto :end
:private
"%APPDIR%\runtime\python.exe" -m dastyar.installer_ui doctor
goto :end
:nopython
echo.
echo  Python was not found. Run install.cmd first.
:end
echo.
pause
