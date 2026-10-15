@echo off
setlocal
pushd "%~dp0" || exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_desktop.ps1" %*
set "result=%errorlevel%"
popd
if not "%result%"=="0" (
  echo Desktop launch failed. Read the error above.
  if not defined CI pause
)
exit /b %result%
