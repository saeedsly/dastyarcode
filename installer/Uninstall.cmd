@echo off
rem ===================================================================
rem  Dastyar (Dast-yar) - safe uninstall
rem  Keeps your chats and settings unless you pass /purge
rem ===================================================================
chcp 65001 >nul 2>&1
setlocal
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
set "DATA=%APPDATA%\Dastyar"
set "PURGE="
if /I "%~1"=="/purge" set "PURGE=1"

echo.
echo  Removing Dastyar shortcuts...

if exist "%APPDIR%\runtime\python.exe" (
  "%APPDIR%\runtime\python.exe" -m dastyar.installer_ui uninstall %1
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$d=[Environment]::GetFolderPath('Desktop');" ^
    "$p=$d+'\Dastyar.lnk'; if(Test-Path $p){Remove-Item $p -Force};" ^
    "$sm=[Environment]::GetFolderPath('Programs')+'\Dastyar';" ^
    "if(Test-Path $sm){Remove-Item $sm -Recurse -Force}" 2>nul
)

if defined PURGE (
  echo.
  echo  Deleting saved chats, settings and the private Python...
  if exist "%DATA%" rd /s /q "%DATA%"
  if exist "%APPDIR%\runtime" rd /s /q "%APPDIR%\runtime"
)

echo.
if defined PURGE (
  echo  Done. Everything was removed.
) else (
  echo  Done. Your chats and settings are still in %DATA%.
  echo  Run "Uninstall.cmd /purge" to delete those as well.
)
echo  You can now delete the program folder itself.
echo.
pause
