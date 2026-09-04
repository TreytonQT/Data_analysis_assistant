@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
  echo [ERROR] Python virtual environment was not found.
  echo Expected: %PYTHONW%
  echo Create it with: py -3.12 -m venv .venv
  pause
  exit /b 1
)

"%PYTHONW%" "%~dp0scripts\dashboard_launcher.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
