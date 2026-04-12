@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0third_party\tyxt-space"
cd /d "%ROOT%"
set "PROJECT_ROOT=%~dp0"

set "DRY_RUN="
if /I "%~1"=="--dry-run" set "DRY_RUN=1"

echo.
echo ==========================================
echo TYXT Space Dev Launcher
if defined DRY_RUN echo [Mode] Dry Run

echo [Step] Checking Node.js and npm...
where node >nul 2>&1
if errorlevel 1 (
  echo [Error] Node.js not found. Install Node.js LTS first.
  echo         Download: https://nodejs.org/
  goto :fail
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [Error] npm not found. Reinstall Node.js to include npm.
  goto :fail
)

for /f "delims=" %%V in ('node -v 2^>nul') do set "NODE_VER=%%V"
for /f "delims=" %%V in ('npm -v 2^>nul') do set "NPM_VER=%%V"
echo [OK] Node !NODE_VER!  npm !NPM_VER!

echo [Step] Installing dependencies if needed...
if not exist "node_modules" (
  if defined DRY_RUN (
    echo [Dry Run] npm install
  ) else (
    npm install
    if errorlevel 1 (
      echo [Error] npm install failed.
      goto :fail
    )
  )
) else (
  echo [OK] node_modules exists, skipping npm install.
)

set "PORT=5173"

:find_port
set "PORT_IN_USE="
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  set "PORT_IN_USE=1"
  set "PORT_PID=%%P"
)

if defined PORT_IN_USE (
  echo [Info] Port %PORT% is in use by PID !PORT_PID!, trying next...
  set /a PORT+=1
  goto :find_port
)

echo [OK] Using port %PORT%
set "URL=http://localhost:%PORT%"
echo [Step] Starting dev server...
echo [Info] URL: %URL%
echo [Info] Press Ctrl+C to stop.

set "TYXT_ROOT_CA=%PROJECT_ROOT%certs\lan\rootCA.pem"
if "%NODE_EXTRA_CA_CERTS%"=="" if exist "%TYXT_ROOT_CA%" (
  set "NODE_EXTRA_CA_CERTS=%TYXT_ROOT_CA%"
  echo [Info] Using local TYXT root CA for backend HTTPS checks.
)

if defined DRY_RUN (
  echo [Dry Run] start "" "%URL%"
  if not "%NODE_EXTRA_CA_CERTS%"=="" echo [Dry Run] set NODE_EXTRA_CA_CERTS=%NODE_EXTRA_CA_CERTS%
  echo [Dry Run] npm run dev -- --host 0.0.0.0 --port %PORT%
  goto :end
)

start "" "%URL%"
npm run dev -- --host 0.0.0.0 --port %PORT%
if errorlevel 1 (
  echo [Error] Dev server exited unexpectedly.
  goto :fail
)

goto :end

:fail
echo.
echo Launcher failed.
exit /b 1

:end
echo.
echo Launcher finished.
exit /b 0


