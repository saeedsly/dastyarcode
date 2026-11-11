@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title Dastyar - AI Assistant
color 0B

:: ===================================================================
::   Dastyar (Dast-yar) - Windows installer
::   Windows 7 SP1, 8, 8.1, 10, 11 (x64). No admin rights required.
::
::   This file is intentionally ASCII-only: cmd.exe on Windows 7 cannot
::   reliably render UTF-8 batch files.  Persian text is printed by
::   Python (dastyar.installer_ui), which handles UTF-8 correctly.
:: ===================================================================

set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
set "PYDIR=%APPDIR%\runtime"
set "PY=%PYDIR%\python.exe"
set "DATA=%APPDATA%\Dastyar"
set "MARK=%DATA%\.installed"
set "PYVER=3.8.10"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip"

call :show_welcome

if exist "%MARK%" goto :already

:: ---------- 1. private python already unpacked? ----------
if exist "%PY%" (
  echo [1/5] Found the private Python in the runtime folder.
  goto :deps
)

:: ---------- 2. system python (3.7+) ----------
set "SYSPY="
for %%P in (python.exe py.exe) do (
  if not defined SYSPY (
    for /f "delims=" %%F in ('where %%P 2^>nul') do (
      if not defined SYSPY set "SYSPY=%%F"
    )
  )
)
if defined SYSPY (
  for /f "tokens=2 delims= " %%V in ('"%SYSPY%" -V 2^>^&1') do set "PYV=%%V"
  echo [1/5] Found system Python: !PYV!
  echo.
  echo   [1] Use this Python ^(fastest, uses about 0 MB extra^)
  echo   [2] Download a private Python ^(fully self-contained^)
  echo.
  set /p CH="  Choose [1/2]: "
  if "!CH!"=="2" goto :download
  set "PY=%SYSPY%"
  goto :deps
)

:: ---------- 3. download the embeddable python ----------
:download
echo.
echo [1/5] Downloading Python %PYVER% ^(about 8 MB^)...
if not exist "%PYDIR%" mkdir "%PYDIR%"
echo       %PYURL%
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%APPDIR%\python.zip' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
  echo.
  echo   [X] Download failed. Check your internet connection or proxy.
  echo   [i] You can also install Python 3.8+ from python.org and run this again.
  pause
  exit /b 1
)
echo       unpacking...
powershell -NoProfile -Command "Expand-Archive -Path '%APPDIR%\python.zip' -DestinationPath '%PYDIR%' -Force"
del /q "%APPDIR%\python.zip" >nul 2>&1

:: embedded python must learn where site-packages lives
if exist "%PYDIR%\python38._pth" (
  > "%PYDIR%\python38._pth" echo python38.zip
  >> "%PYDIR%\python38._pth" echo .
  >> "%PYDIR%\python38._pth" echo Lib\site-packages
  >> "%PYDIR%\python38._pth" echo import site
)
if not exist "%PYDIR%\Lib\site-packages" mkdir "%PYDIR%\Lib\site-packages"
if not exist "%PY%" (
  echo   [X] Could not unpack Python.
  pause
  exit /b 1
)
set "PY=%PYDIR%\python.exe"

:: ---------- 4. optional packages ----------
:deps
echo.
echo [2/5] Preparing the package manager...
"%PY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :deps_install

if exist "%PYDIR%\python38._pth" findstr /C:"import site" "%PYDIR%\python38._pth" >nul 2>&1
if not errorlevel 1 goto :pip_bootstrap
if exist "%PYDIR%\python38._pth" >> "%PYDIR%\python38._pth" echo import site

:pip_bootstrap
echo       downloading pip...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/pip/3.8/get-pip.py' -OutFile '%TEMP%\get-pip.py' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
  echo       [!] pip was not installed - the assistant still works without it.
  goto :deps_done
)
"%PY%" "%TEMP%\get-pip.py" --quiet --disable-pip-version-check --no-warn-script-location >nul 2>&1
del /q "%TEMP%\get-pip.py" >nul 2>&1
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo       [!] pip was not installed - the assistant still works without it.
  goto :deps_done
)

:deps_install
echo [3/5] Installing optional extras ^(natural voice + native window^)...
"%PY%" -m pip install --quiet --disable-pip-version-check --no-warn-script-location edge-tts >nul 2>&1
if errorlevel 1 echo       - edge-tts skipped ^(the Windows SAPI voice still works^)
"%PY%" -m pip install --quiet --disable-pip-version-check --no-warn-script-location pywebview >nul 2>&1
if errorlevel 1 echo       - pywebview skipped ^(the browser window is used instead^)

:deps_done
:: ---------- 5. data folder + shortcuts ----------
echo.
echo [4/5] Preparing your data folder...
if not exist "%DATA%" mkdir "%DATA%"
if not exist "%DATA%\logs" mkdir "%DATA%\logs"

echo.
echo [5/5] Creating desktop and Start Menu shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell);" ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$t=$s.CreateShortcut($d+'\Dastyar.lnk');" ^
  "$t.TargetPath='%PY%';" ^
  "$t.Arguments='-m dastyar run';" ^
  "$t.WorkingDirectory='%APPDIR%';" ^
  "$t.IconLocation='%APPDIR%\dastyar\assets\icon.ico';" ^
  "$t.Description='Dastyar - your AI assistant';" ^
  "$t.Save();" ^
  "$sm=[Environment]::GetFolderPath('Programs')+'\Dastyar';" ^
  "if(-not (Test-Path $sm)){New-Item -ItemType Directory -Path $sm | Out-Null};" ^
  "$t2=$s.CreateShortcut($sm+'\Dastyar.lnk');" ^
  "$t2.TargetPath='%PY%';" ^
  "$t2.Arguments='-m dastyar run';" ^
  "$t2.WorkingDirectory='%APPDIR%';" ^
  "$t2.IconLocation='%APPDIR%\dastyar\assets\icon.ico';" ^
  "$t2.Save()"

if not exist "%DATA%\config.json" (
  "%PY%" -c "import sys;sys.path.insert(0,'%APPDIR%');from dastyar.config import Settings,ensure_data_dir;ensure_data_dir();_s=Settings();_s.set('ui.shutdown_when_idle',True);_s.save()" >nul 2>&1
)

echo installed %DATE% %TIME% > "%MARK%"

:: ---------- done ----------
call :show_done

set /p RUN="  Start Dastyar now? [Y/n]: "
if /I "%RUN%"=="n" exit /b 0
start "" "%PY%" -m dastyar run
exit /b 0

:already
echo.
echo   Dastyar is already installed - starting it now.
start "" "%PY%" -m dastyar run
exit /b 0

:: ================= helpers =================
:show_welcome
echo.
echo  ==================================================
echo    D A S T Y A R   ^|   your AI assistant
echo  ==================================================
echo.
echo    Installs into this folder, no admin rights needed.
echo.
"%PY%" -m dastyar.installer_ui welcome 2>nul
exit /b 0

:show_done
echo.
echo  ==================================================
echo    Installation complete!
echo  ==================================================
echo.
"%PY%" -m dastyar.installer_ui done 2>nul
exit /b 0
