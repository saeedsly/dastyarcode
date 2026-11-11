@echo off
rem ASCII-only on purpose (cmd.exe on Windows 7 cannot render UTF-8 scripts)
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title Dastyar - build standalone exe
cd /d "%~dp0\.."

echo.
echo  === building Dastyar.exe (PyInstaller) ===
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [!] Python 3.8+ is required to BUILD. Install from python.org first.
  pause & exit /b 1
)

if not exist ".venv-build" (
  echo  [1/4] creating build venv...
  python -m venv .venv-build || (echo venv failed & pause & exit /b 1)
)
call .venv-build\Scripts\activate.bat

echo  [2/4] installing pyinstaller...
python -m pip install --quiet --upgrade pip pyinstaller || (echo pip failed & pause & exit /b 1)

echo  [3/4] building...
python -m PyInstaller --noconfirm --clean dastyar.spec || (echo build failed & pause & exit /b 1)

echo  [4/4] zipping...
powershell -NoProfile -Command "if(Test-Path 'dist\Dastyar-win64.zip'){Remove-Item 'dist\Dastyar-win64.zip' -Force}; Compress-Archive -Path 'dist\Dastyar\*' -DestinationPath 'dist\Dastyar-win64.zip' -CompressionLevel Optimal"

echo.
echo  ============================================
echo   [OK] dist\Dastyar\Dastyar.exe
echo   [OK] dist\Dastyar-win64.zip   (share this with friends)
echo  ============================================
echo.
pause
