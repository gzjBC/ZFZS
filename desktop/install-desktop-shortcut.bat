@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_desktop_shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Failed to create the desktop shortcut.
  pause
  exit /b 1
)
echo.
echo Desktop shortcut is ready.
pause
