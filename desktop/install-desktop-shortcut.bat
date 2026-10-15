@echo off
setlocal
pushd "%~dp0" || exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_desktop_shortcut.ps1" %*
set "result=%errorlevel%"
popd
if not "%result%"=="0" (
  echo.
  echo Failed to create the desktop shortcut.
  if not defined CI pause
  exit /b %result%
)
echo.
echo Desktop shortcut is ready.
if not defined CI pause
exit /b 0
