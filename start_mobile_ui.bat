@echo off
setlocal EnableExtensions

title TYXT Mobile UI Start
cd /d "%~dp0"

set "MOBILE_DIR=%~dp0third_party\tyxt_mobile_frontend"

echo.
echo ==========================================
echo   TYXT Mobile UI Start
echo ==========================================
echo.
echo [INFO] Repo root : %~dp0
echo [INFO] Mobile dir: %MOBILE_DIR%
echo.

if not exist "%MOBILE_DIR%\package.json" (
  echo [ERROR] package.json not found:
  echo         %MOBILE_DIR%\package.json
  echo [HINT] Ensure third_party\tyxt_mobile_frontend exists.
  echo.
  pause
  exit /b 1
)

where npm >nul 2>nul
if not "%errorlevel%"=="0" (
  echo [ERROR] npm not found in PATH.
  echo [HINT] Install Node.js (LTS) and reopen terminal.
  echo.
  pause
  exit /b 1
)

cd /d "%MOBILE_DIR%"

if not exist "node_modules" (
  echo [INFO] node_modules not found, running npm install ...
  call npm install
  if not "%errorlevel%"=="0" (
    echo [ERROR] npm install failed.
    echo.
    pause
    exit /b 1
  )
)

echo.
echo [OK] Starting mobile UI dev server on:
echo      http://127.0.0.1:5173
echo      http://0.0.0.0:5173
echo [TIP] Keep this window open while using mobile UI.
echo.

call npm run dev -- --host 0.0.0.0 --port 5173
set "RC=%errorlevel%"

echo.
if not "%RC%"=="0" (
  echo [ERROR] Mobile UI exited with code: %RC%
) else (
  echo [OK] Mobile UI exited.
)
echo.
pause
exit /b %RC%
