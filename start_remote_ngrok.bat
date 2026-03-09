@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT Remote Start (Ngrok)
cd /d "%~dp0"
set "TYXT_REMOTE_NGROK_VER=2026-03-09 18:20 MOBILE-CROSSLOGIN"

set "BACKEND_BASE=http://127.0.0.1:5000"
set "HEALTH_URL=%BACKEND_BASE%/health"
set "SCRIPT_RC=0"
set "NGROK_EXE=ngrok"
set "MIN_NGROK_VER=3.20.0"

echo.
echo ==========================================
echo   TYXT Remote Start (Ngrok Fallback)
echo ==========================================
echo [INFO] Script version: %TYXT_REMOTE_NGROK_VER%
echo [INFO] Script path   : %~f0
echo.

echo [1/4] Checking ngrok ...
where ngrok >nul 2>nul
if "%errorlevel%"=="0" (
  for /f "delims=" %%P in ('where ngrok') do (
    set "NGROK_EXE=%%P"
    goto ngrok_ok
  )
)
if exist "%~dp0tools\ngrok.exe" (
  set "NGROK_EXE=%~dp0tools\ngrok.exe"
  goto ngrok_ok
)

echo [WARN] ngrok not found. Trying winget install ...
where winget >nul 2>nul
if not "%errorlevel%"=="0" goto ngrok_missing
winget install -e --id Ngrok.Ngrok --accept-package-agreements --accept-source-agreements
where ngrok >nul 2>nul
if "%errorlevel%"=="0" (
  for /f "delims=" %%P in ('where ngrok') do (
    set "NGROK_EXE=%%P"
    goto ngrok_ok
  )
)

:ngrok_missing
echo [ERROR] ngrok is required but not installed.
echo [HINT] Install one of the following then re-run this script:
echo        winget install -e --id Ngrok.Ngrok
echo        https://ngrok.com/download
goto failed

:ngrok_ok
echo [OK] ngrok: %NGROK_EXE%
set "NGROK_VER="
for /f "tokens=3" %%V in ('"%NGROK_EXE%" version 2^>nul') do set "NGROK_VER=%%V"
if not defined NGROK_VER (
  echo [WARN] Cannot determine ngrok version from CLI output.
) else (
  echo [INFO] ngrok version: %NGROK_VER%
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { if([version]::Parse('%NGROK_VER%') -ge [version]::Parse('%MIN_NGROK_VER%')) { exit 0 } else { exit 1 } } catch { exit 1 }"
  if not "%errorlevel%"=="0" (
    echo [WARN] ngrok version is too old. Need >= %MIN_NGROK_VER%.
    echo [INFO] Trying automatic update: "%NGROK_EXE%" update
    "%NGROK_EXE%" update
    set "NGROK_VER="
    for /f "tokens=3" %%V in ('"%NGROK_EXE%" version 2^>nul') do set "NGROK_VER=%%V"
    if defined NGROK_VER echo [INFO] ngrok version after update: !NGROK_VER!
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { if([version]::Parse('!NGROK_VER!') -ge [version]::Parse('%MIN_NGROK_VER%')) { exit 0 } else { exit 1 } } catch { exit 1 }"
    if not "!errorlevel!"=="0" (
      echo [ERROR] ngrok version is still too old.
      echo [HINT] Download/update manually: https://ngrok.com/download
      goto failed
    )
  )
)
echo [INFO] If ngrok reports auth error, run:
echo        ngrok config add-authtoken ^<YOUR_TOKEN^>
echo.

echo [2/4] Restarting backend in HTTP mode on port 5000 ...
echo [INFO] Enabling cross-origin session cookie for HTTPS tunnel:
echo [INFO]   SESSION_COOKIE_SAMESITE=None
echo [INFO]   SESSION_COOKIE_SECURE=1
echo [INFO] Cleaning old backend/tunnel leftovers ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ps=Get-CimInstance Win32_Process | Where-Object { ($_.Name -match 'cmd.exe|powershell.exe') -and ((([string]$_.CommandLine) -like '*start_agent.bat*') -or ((([string]$_.CommandLine) -like '*ollama_multi_agent.py*')) -or ((([string]$_.CommandLine) -like '*ngrok.exe*http*127.0.0.1:5000*')) -or ((([string]$_.CommandLine) -like '*cloudflared*tunnel*'))) }; foreach($p in $ps){ try{ Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch{} }"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ps=Get-CimInstance Win32_Process | Where-Object { ($_.Name -match 'python.exe|pythonw.exe') -and ((([string]$_.CommandLine) -like '*ollama_multi_agent.py*')) }; foreach($p in $ps){ try{ Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch{} }"
taskkill /F /IM ngrok.exe >nul 2>nul
taskkill /F /IM cloudflared.exe >nul 2>nul
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if($p){$p | ForEach-Object { Write-Output $_ }}"') do (
  taskkill /F /PID %%P >nul 2>nul
)
timeout /t 1 /nobreak >nul
start "TYXT Backend HTTP" cmd /k set TYXT_FORCE_HTTP=1^& set TYXT_NO_BROWSER=1^& set TYXT_WINDOW_TITLE=TYXT Backend HTTP^& set SESSION_COOKIE_SAMESITE=None^& set SESSION_COOKIE_SECURE=1^& call "%~dp0start_agent.bat"

echo [3/4] Waiting backend health ...
set /a TRY=0
:wait_backend
set /a TRY+=1
where curl.exe >nul 2>nul
if "%errorlevel%"=="0" (
  curl.exe -sS -o nul --noproxy "*" --max-time 2 "%HEALTH_URL%" >nul 2>nul
  if "!errorlevel!"=="0" goto backend_ready
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%HEALTH_URL%' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }"
  if "!errorlevel!"=="0" goto backend_ready
)
if !TRY! GEQ 180 (
  echo [ERROR] Backend health check timeout.
  echo [HINT] Check the "TYXT Backend HTTP" window logs.
  goto failed
)
if !TRY! EQU 30 echo [INFO] Still waiting... backend cold start can take around 1-2 minutes.
timeout /t 1 /nobreak >nul
goto wait_backend

:backend_ready
echo [OK] Backend is ready at %BACKEND_BASE%

echo [4/4] Starting ngrok tunnel ...
taskkill /F /IM ngrok.exe >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ps=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cmd.exe' -and ((([string]$_.CommandLine) -like '*ngrok.exe*http*127.0.0.1:5000*')) }; foreach($p in $ps){ try{ Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch{} }"
start "TYXT Ngrok Tunnel" cmd /k ""%NGROK_EXE%" http 127.0.0.1:5000"

echo [INFO] Waiting ngrok public URL ...
set "PUBLIC_URL="
for /l %%I in (1,1,45) do (
  if %%I GEQ 8 (
    tasklist /FI "IMAGENAME eq ngrok.exe" | find /I "ngrok.exe" >nul
    if not "!errorlevel!"=="0" (
      echo [ERROR] ngrok process is not running.
      echo [HINT] Check the "TYXT Ngrok Tunnel" window for auth/version errors.
      echo [HINT] Usually fix with:
      echo [HINT]   ngrok update
      echo [HINT]   ngrok config add-authtoken ^<YOUR_TOKEN^>
      goto failed
    )
  )
  for /f "usebackq delims=" %%U in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $j=Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2; $u = $j.tunnels | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1 -ExpandProperty public_url; if($u){ Write-Output $u } } catch {}"`) do (
    set "PUBLIC_URL=%%U"
  )
  if defined PUBLIC_URL goto url_ready
  timeout /t 1 /nobreak >nul
)

echo [WARN] Could not fetch ngrok public URL from local API.
echo [HINT] Open the "TYXT Ngrok Tunnel" window and copy the https forwarding URL.
goto done

:url_ready
echo [OK] Public URL:
echo      !PUBLIC_URL!
start "" "!PUBLIC_URL!" >nul 2>nul
echo.
echo [MOBILE] API Base example:
echo         !PUBLIC_URL!/v1
echo [MOBILE] If WebUI configured "手机关联密码", fill it in mobile API Key.

:done
echo.
echo [INFO] Keep these windows open while users are connected:
echo        1) TYXT Backend HTTP
echo        2) TYXT Ngrok Tunnel
echo [TIP] Run stop_all.bat to stop quickly.
echo.
pause
exit /b 0

:failed
set "SCRIPT_RC=1"
echo.
echo [FAILED] start_remote_ngrok.bat did not finish successfully.
echo [HINT] Run setup_start_cn.bat first if dependencies are missing.
echo.
pause
exit /b %SCRIPT_RC%
