@echo off
setlocal

title TYXT LAN HTTPS Easy Start
cd /d "%~dp0"

echo.
echo ==========================================
echo   TYXT LAN HTTPS Easy Start
echo ==========================================
echo.

set "PS_CMD=powershell -NoProfile -ExecutionPolicy Bypass"
set "CERT_FILE=%~dp0certs\lan\server.pem"
set "KEY_FILE=%~dp0certs\lan\server-key.pem"
set "ROOTCA_FILE=%~dp0certs\lan\rootCA.cer"
set "ZERO_CLIENT_FILE=%~dp0client_join_lan_ui_zero_input.bat"
set "ZERO_CLIENT_MARKER=TYXT_ZERO_BAT_VERSION=20260302.7"
set "NEED_SETUP=0"

if not exist "%CERT_FILE%" set "NEED_SETUP=1"
if not exist "%KEY_FILE%" set "NEED_SETUP=1"
if not exist "%ROOTCA_FILE%" set "NEED_SETUP=1"
if not exist "%ZERO_CLIENT_FILE%" set "NEED_SETUP=1"

if "%NEED_SETUP%"=="0" (
  findstr /C:"%ZERO_CLIENT_MARKER%" "%ZERO_CLIENT_FILE%" >nul 2>nul
  if errorlevel 1 set "NEED_SETUP=1"
)

if "%NEED_SETUP%"=="0" (
  echo [1/2] LAN HTTPS certificates and zero-input client file found. Skip setup.
) else (
  echo [1/2] Preparing LAN HTTPS certificates...
  %PS_CMD% -File "%~dp0tools\setup_lan_https.ps1" -AutoInstallMkcert
  if not "%errorlevel%"=="0" (
    echo.
    echo [WARN] LAN HTTPS setup failed. Fallback to normal startup.
    echo [WARN] You can rerun tools\setup_lan_https.ps1 later.
    echo.
  )
)

echo [2/2] Starting backend...
call "%~dp0start_agent.bat"
endlocal
