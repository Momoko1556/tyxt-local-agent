@echo off
setlocal EnableExtensions

title TYXT Project Setup
cd /d "%~dp0"

echo.
echo ==========================================
echo   TYXT Project Setup
echo ==========================================
echo.

set "PYTHON_CMD="
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "OLLAMA_MODEL=deepseek-r1:8b"

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
  echo [ERROR] Python not found. Please install Python 3.10+ and add it to PATH.
  echo.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo [1/4] Creating virtual environment .venv ...
  %PYTHON_CMD% -m venv .venv
  if not "%errorlevel%"=="0" (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
  )
) else (
  echo [1/4] Virtual environment already exists.
)

set "PYTHON_CMD=%VENV_PY%"
echo [INFO] Using interpreter: %PYTHON_CMD%

echo [2/4] Upgrading pip/setuptools/wheel...
"%PYTHON_CMD%" -m pip install --upgrade pip setuptools wheel
if not "%errorlevel%"=="0" (
  echo [ERROR] pip upgrade failed.
  pause
  exit /b 1
)

echo [3/4] Installing dependencies from requirements.txt...
"%PYTHON_CMD%" -m pip install -r requirements.txt
if not "%errorlevel%"=="0" (
  echo [ERROR] Dependency installation failed.
  pause
  exit /b 1
)

if not exist ".env" if exist ".env.example" (
  copy /Y ".env.example" ".env" >nul
  echo [INFO] Created .env from .env.example
)

call :resolve_ollama_model

echo [4/5] Initializing empty ChromaDB...
"%PYTHON_CMD%" tools\init_chromadb.py
if not "%errorlevel%"=="0" (
  echo [ERROR] ChromaDB initialization failed.
  pause
  exit /b 1
)

if /I "%TYXT_SKIP_OLLAMA_SETUP%"=="1" (
  echo [5/5] Skipping Ollama bootstrap because TYXT_SKIP_OLLAMA_SETUP=1
) else (
  echo [5/5] Ensuring Ollama and model: %OLLAMA_MODEL%
  call :ensure_ollama
  if not "%errorlevel%"=="0" (
    echo [WARN] Ollama auto-install failed.
    echo [WARN] Install Ollama manually, then run: ollama pull %OLLAMA_MODEL%
  ) else (
    call :ensure_ollama_model
    if not "%errorlevel%"=="0" (
      echo [WARN] Model pull failed. You can retry manually:
      echo [WARN]   ollama pull %OLLAMA_MODEL%
    )
  )
)

echo.
echo [OK] Setup completed successfully.
echo [TIP] Next step: run start_agent.bat
echo.
pause
exit /b 0

:resolve_ollama_model
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%~A"=="MODEL_NAME" (
      set "OLLAMA_MODEL=%%~B"
    )
  )
)
set "OLLAMA_MODEL=%OLLAMA_MODEL:"=%"
if "%OLLAMA_MODEL%"=="" set "OLLAMA_MODEL=deepseek-r1:8b"
exit /b 0

:ensure_ollama
where ollama >nul 2>nul
if "%errorlevel%"=="0" exit /b 0

echo [INFO] Ollama not found. Trying winget install...
where winget >nul 2>nul
if "%errorlevel%"=="0" (
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
  if "%errorlevel%"=="0" (
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
    where ollama >nul 2>nul
    if "%errorlevel%"=="0" exit /b 0
  )
)

echo [INFO] winget unavailable or install failed. Trying choco...
where choco >nul 2>nul
if "%errorlevel%"=="0" (
  choco install ollama -y --no-progress
  if "%errorlevel%"=="0" (
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
    where ollama >nul 2>nul
    if "%errorlevel%"=="0" exit /b 0
  )
)

exit /b 1

:ensure_ollama_model
where powershell >nul 2>nul
if "%errorlevel%"=="0" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -WindowStyle Hidden -FilePath 'ollama' -ArgumentList 'serve'" >nul 2>nul
) else (
  start "" /min ollama serve
)
timeout /t 2 /nobreak >nul

ollama show "%OLLAMA_MODEL%" >nul 2>nul
if "%errorlevel%"=="0" (
  echo [INFO] Ollama model already available: %OLLAMA_MODEL%
  exit /b 0
)

echo [INFO] Pulling Ollama model: %OLLAMA_MODEL%
ollama pull "%OLLAMA_MODEL%"
if not "%errorlevel%"=="0" exit /b 2

echo [INFO] Ollama model ready: %OLLAMA_MODEL%
exit /b 0
