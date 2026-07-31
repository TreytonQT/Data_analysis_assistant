@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8000"
set "HEALTH_URL=%APP_URL%/api/health"
set "RUNTIME_DIR=%~dp0.tmp"
set "STDOUT_LOG=%RUNTIME_DIR%\dashboard.stdout.log"
set "STDERR_LOG=%RUNTIME_DIR%\dashboard.stderr.log"
set "PID_FILE=%RUNTIME_DIR%\dashboard.pid"

call :dashboard_ready
if not errorlevel 1 goto open_dashboard

if not exist "%PYTHON%" (
  echo [ERROR] Python virtual environment was not found.
  echo Expected: %PYTHON%
  echo Create it with: py -3.12 -m venv .venv
  exit /b 1
)

"%PYTHON%" -c "import fastapi, uvicorn, multipart, pandas, pyarrow, openpyxl, xlrd" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python dependencies are incomplete.
  echo Run: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

if not exist "%~dp0frontend\dist\index.html" (
  echo [ERROR] The React production build was not found at frontend\dist\index.html.
  echo Run: cd frontend ^&^& npm.cmd ci ^&^& npm.cmd run build
  exit /b 1
)

rem A previous click may already have started this dashboard. Re-check after
rem validating the local installation so repeated clicks simply open the page.
call :dashboard_ready
if not errorlevel 1 goto open_dashboard

"%PYTHON%" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); used=s.connect_ex(('127.0.0.1',8000)) == 0; s.close(); sys.exit(1 if used else 0)"
if errorlevel 1 (
  echo [ERROR] Port 8000 is already occupied. Stop the existing process, then try again.
  echo To inspect it: netstat -ano ^| findstr :8000
  exit /b 1
)

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
del /q "%STDOUT_LOG%" "%STDERR_LOG%" "%PID_FILE%" >nul 2>&1

echo Starting the local dashboard at %APP_URL% ...
rem Use cmd's native background launch: some Windows environments expose both
rem Path and PATH, which makes PowerShell Start-Process fail before Python starts.
start "" /b "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 1>"%STDOUT_LOG%" 2>"%STDERR_LOG%"
if errorlevel 1 (
  echo [ERROR] The API process could not be started.
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$deadline = (Get-Date).AddSeconds(30); do { try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo [ERROR] The API did not become healthy within 30 seconds.
  if exist "%STDERR_LOG%" type "%STDERR_LOG%"
  echo Logs: %STDOUT_LOG% and %STDERR_LOG%
  if exist "%PID_FILE%" powershell.exe -NoProfile -Command "$id = Get-Content -LiteralPath '%PID_FILE%' -ErrorAction SilentlyContinue; if ($id) { Stop-Process -Id $id -ErrorAction SilentlyContinue }"
  exit /b 1
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8000 .*LISTENING"') do (
  > "%PID_FILE%" echo %%P
  goto open_dashboard
)

:open_dashboard
echo Dashboard is ready. Opening %APP_URL% ...
start "" "%APP_URL%"
exit /b 0

:dashboard_ready
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
  "try { $health = Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 2; $page = Invoke-WebRequest -UseBasicParsing -Uri '%APP_URL%/' -TimeoutSec 3; if ($health.StatusCode -eq 200 -and $page.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%
