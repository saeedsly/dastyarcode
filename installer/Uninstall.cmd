@echo off
rem ===================================================================
rem  دستیار / Dastyar — safe uninstall (keeps your chats & settings)
rem  Remove with:  Uninstall.cmd  /purge   to also delete data
rem ===================================================================
chcp 65001 >nul 2>&1
setlocal
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
set "DATA=%APPDATA%\Dastyar"
set "PURGE="
if /I "%~1"=="/purge" set "PURGE=1"

echo.
echo  حذف دستیار...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$p=$d+'\دستیار.lnk'; if(Test-Path $p){Remove-Item $p -Force};" ^
  "$sm=[Environment]::GetFolderPath('Programs')+'\Dastyar';" ^
  "if(Test-Path $sm){Remove-Item $sm -Recurse -Force}"

if defined PURGE (
  echo  داده‌ها و گفتگوهای ذخیره‌شده پاک می‌شوند: %DATA%
  if exist "%DATA%" rd /s /q "%DATA%"
  if exist "%APPDIR%\runtime" rd /s /q "%APPDIR%\runtime"
)

echo.
echo  ✅ حذف شد. اگر /purge ندادی، تنظیمات و گفتگوها در %DATA% مانده‌اند.
echo  نکته: فایل‌های برنامه را دستی از همین پوشه پاک کن.
echo.
pause
