@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title دستیار - Dastyar
color 0B

:: ===================================================================
::              دستیار  Dastyar  —  Windows installer
::   Works on Windows 7 SP1, 8, 8.1, 10 and 11 (32/64-bit), NO admin.
:: ===================================================================

set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
set "PYDIR=%APPDIR%\runtime"
set "PY=%PYDIR%\python.exe"
set "DATA=%APPDATA%\Dastyar"
set "MARK=%DATA%\.installed"
set "PYVER=3.8.10"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip"

echo.
echo  ==================================================
echo   د س ت ی ا ر   ^|   Dastyar  AI Assistant
echo  ==================================================
echo.
echo   نصب کامل بدون نیاز به دسترسی مدیر - بدون نصب پایتون
echo   (Installing a private Python for this app only)
echo.

if exist "%MARK%" goto :already

:: ---------- 1. check for a private python runtime ----------
if exist "%PY%" (
  echo [1/4] Python found in runtime folder
  goto :deps
)

:: ---------- 2. try system python (3.7+) ----------
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
  echo [1/4] Found system Python: !PYV!
  echo.
  echo   گزینه‌ها:
  echo     1^) استفاده از همین پایتون (سریع)
  echo     2^) دانلود پایتون اختصاصی و مستقل (مطمئن‌ترین)
  echo.
  set /p CH="  انتخاب [1/2]: "
  if "!CH!"=="2" goto :download
  set "PY=%SYSPY%"
  goto :deps
)

:: ---------- 3. download a private embedded python ----------
:download
echo.
echo [1/4] Downloading Python %PYVER% (about 8 MB)...
if not exist "%PYDIR%" mkdir "%PYDIR%"
echo   -> %PYURL%
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%APPDIR%\python.zip' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
  echo.
  echo   [X] دانلود ناموفق بود. اینترنت یا فیلترشکن را بررسی کن.
  echo   [i] می‌توانی دستی Python 3.8 از python.org نصب کنی و دوباره اجرا کنی.
  pause
  exit /b 1
)
echo   -> unpacking...
powershell -NoProfile -Command "Expand-Archive -Path '%APPDIR%\python.zip' -DestinationPath '%PYDIR%' -Force"
del /q "%APPDIR%\python.zip" >nul 2>&1

:: embedded python needs the ._pth file so it can import from lib\site-packages
if exist "%PYDIR%\python38._pth" (
  > "%PYDIR%\python38._pth" echo python38.zip
  >> "%PYDIR%\python38._pth" echo .
  >> "%PYDIR%\python38._pth" echo Lib\site-packages
  >> "%PYDIR%\python38._pth" echo import site
)
if exist "%PYDIR%\python38.zip" if not exist "%PYDIR%\Lib" mkdir "%PYDIR%\Lib"
if not exist "%PYDIR%\Lib\site-packages" mkdir "%PYDIR%\Lib\site-packages"
if not exist "%PY%" (
  echo   [X] استخراج پایتون ناموفق بود.
  pause
  exit /b 1
)
set "PY=%PYDIR%\python.exe"

:deps
echo.
echo [2/4] Preparing package manager...

:: The embedded Python has no pip: bootstrap it (needs the "import site"
:: line we just wrote into python38._pth).
"%PY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :deps_install
if exist "%PYDIR%\python38._pth" findstr /C:"import site" "%PYDIR%\python38._pth" >nul 2>&1
if not errorlevel 1 goto :pip_ready
if exist "%PYDIR%\python38._pth" >>"%PYDIR%\python38._pth" echo import site
:pip_ready
echo   downloading pip bootstrap...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/pip/3.8/get-pip.py' -OutFile '%TEMP%\get-pip.py' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
  echo    - pip نصب نشد ^(برنامه بدون بسته‌های اختیاری هم کار می‌کند^)
  goto :deps_done
)
"%PY%" "%TEMP%\get-pip.py" --quiet --disable-pip-version-check --no-warn-script-location >nul 2>&1
del /q "%TEMP%\get-pip.py" >nul 2>&1
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo    - pip نصب نشد ^(برنامه بدون بسته‌های اختیاری هم کار می‌کند^)
  goto :deps_done
)

:deps_install
echo [2/4] Installing optional quality packages ^(voice, browser, window^)...
"%PY%" -m pip install --quiet --disable-pip-version-check --no-warn-script-location edge-tts >nul 2>&1
if errorlevel 1 echo    - edge-tts نصب نشد ^(صدا با SAPI ویندوز کار می‌کند^)
"%PY%" -m pip install --quiet --disable-pip-version-check --no-warn-script-location pywebview >nul 2>&1
if errorlevel 1 echo    - pywebview نصب نشد ^(پنجره در مرورگر باز می‌شود^)

:: ---------- 4. data folder + shortcuts ----------
:deps_done
echo.
echo [3/4] Preparing user data folder...
if not exist "%DATA%" mkdir "%DATA%"
if not exist "%DATA%\logs" mkdir "%DATA%\logs"

echo.
echo [4/4] Creating desktop and Start Menu shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell);" ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$t=$s.CreateShortcut($d+'\دستیار.lnk');" ^
  "$t.TargetPath='%PY%';" ^
  "$t.Arguments='-m dastyar run';" ^
  "$t.WorkingDirectory='%APPDIR%';" ^
  "$t.IconLocation='%APPDIR%\dastyar\assets\icon.ico';" ^
  "$t.Description='دستیار هوشمند - Dastyar AI';" ^
  "$t.Save();" ^
  "$sm=[Environment]::GetFolderPath('Programs')+'\Dastyar';" ^
  "if(-not (Test-Path $sm)){New-Item -ItemType Directory -Path $sm | Out-Null};" ^
  "$t2=$s.CreateShortcut($sm+'\دستیار.lnk');" ^
  "$t2.TargetPath='%PY%';" ^
  "$t2.Arguments='-m dastyar run';" ^
  "$t2.WorkingDirectory='%APPDIR%';" ^
  "$t2.IconLocation='%APPDIR%\dastyar\assets\icon.ico';" ^
  "$t2.Save()"

echo installed %DATE% %TIME% > "%MARK%"

:: ---------- 5. first run ----------
echo.
echo  ==================================================
echo   ✅ نصب کامل شد!
echo   ==================================================
echo.
echo   میان‌بر «دستیار» روی دسکتاپ و در منوی Start ساخته شد.
echo   اولین بار که باز کن، صفحه‌ی تنظیمات کلید API باز می‌شود.
echo.
echo   [i] برای شروع رایگان، OpenRouter یا Gemini یا Groq را انتخاب کن.
echo   [i] بدون کلید هم «حالت نمایشی» کار می‌کند.
echo.
set /p RUN="  الان باز شود؟ [Y/n]: "
if /I "%RUN%"=="n" exit /b 0
if not exist "%DATA%\config.json" (
  "%PY%" -c "import sys;sys.path.insert(0,'%APPDIR%');from dastyar.config import Settings,ensure_data_dir;ensure_data_dir();_s=Settings();_s.set('ui.shutdown_when_idle',True);_s.save();print('config ready')"
)
start "" "%PY%" -m dastyar run
exit /b 0

:already
echo.
echo   دستیار قبلاً نصب شده است. در حال اجرا...
start "" "%PY%" -m dastyar run
exit /b 0
