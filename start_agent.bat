@echo off
setlocal

title Ollama Multi-Agent Launcher
cd /d "%~dp0"

echo.
echo ==========================================
echo   Starting Ollama Multi-Agent backend
echo   Script: ollama_multi_agent.py
echo ==========================================
echo.

set "PYTHON_CMD="
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  set "PYTHON_CMD=%VENV_PY%"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_CMD=python"
  ) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
      set "PYTHON_CMD=py -3"
    )
  )
)

if "%PYTHON_CMD%"=="" (
  echo [ERROR] Python not found. Please install Python and add it to PATH.
  echo.
  pause
  exit /b 1
)

echo Using interpreter: %PYTHON_CMD%
if exist "%VENV_PY%" (
  echo [INFO] Virtual environment detected: .venv
)
echo.

set "TYXT_UI_HTML=%~dp0frontend\TYXT_UI.html"
set "TYXT_SSL_CERT_FILE=%~dp0certs\lan\server.pem"
set "TYXT_SSL_KEY_FILE=%~dp0certs\lan\server-key.pem"
set "USE_HTTPS=0"
if exist "%TYXT_SSL_CERT_FILE%" if exist "%TYXT_SSL_KEY_FILE%" set "USE_HTTPS=1"

if "%USE_HTTPS%"=="1" (
  set "UI_URL=https://127.0.0.1:5000/"
  set "HEALTH_URL=https://127.0.0.1:5000/health"
) else (
  set "TYXT_SSL_CERT_FILE="
  set "TYXT_SSL_KEY_FILE="
  set "UI_URL=http://127.0.0.1:5000/"
  set "HEALTH_URL=http://127.0.0.1:5000/health"
)

if exist "%TYXT_UI_HTML%" (
  echo TYXT_UI_HTML: %TYXT_UI_HTML%
) else (
  echo [WARN] TYXT_UI_HTML not found: %TYXT_UI_HTML%
  echo [WARN] Backend route "/" may not be able to serve UI.
)
if "%USE_HTTPS%"=="1" (
  echo HTTPS cert : %TYXT_SSL_CERT_FILE%
  echo HTTPS key  : %TYXT_SSL_KEY_FILE%
) else (
  echo [INFO] HTTPS disabled (cert files not found under certs\lan\)
)

echo Web UI URL : %UI_URL%
echo Health URL : %HEALTH_URL%
echo Browser will open after backend starts...
start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process '%UI_URL%'"
echo.

%PYTHON_CMD% "%~dp0ollama_multi_agent.py"
set "EXIT_CODE=%errorlevel%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Backend exited with code: %EXIT_CODE%
) else (
  echo [OK] Backend exited.
)
echo.
pause
exit /b %EXIT_CODE%
