@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT Remote Easy Start (No Domain)
cd /d "%~dp0"
set "TYXT_REMOTE_EASY_VER=2026-03-25 16:25 AUTO-RECONNECT"

set "BACKEND_BASE_HTTP=http://127.0.0.1:5000"
set "BACKEND_BASE_HTTPS=https://127.0.0.1:5000"
set "HEALTH_URL_HTTP=%BACKEND_BASE_HTTP%/health"
set "HEALTH_URL_HTTPS=%BACKEND_BASE_HTTPS%/health"
set "BACKEND_SCHEME=NONE"
set "BACKEND_BASE="
set "TUNNEL_TLS_ARGS="
set "SCRIPT_RC=0"
set "CLOUDFLARED_EXE=cloudflared"
set "CF_RETRY_DELAY_SEC=3"
set "CF_RETRY_MAX=0"
set "CF_RETRY_COUNT=0"
set "CF_HOSTS_FALLBACK_DONE=0"

echo.
echo ==========================================
echo   TYXT Remote Easy Start (No Domain)
echo ==========================================
echo [INFO] Script version: %TYXT_REMOTE_EASY_VER%
echo [INFO] Script path   : %~f0
echo.

echo [1/3] Checking cloudflared ...
where cloudflared >nul 2>nul
if "%errorlevel%"=="0" (
  set "CLOUDFLARED_EXE=cloudflared"
  goto cloudflared_ok
)
if exist "%ProgramFiles%\cloudflared\cloudflared.exe" (
  set "CLOUDFLARED_EXE=%ProgramFiles%\cloudflared\cloudflared.exe"
  goto cloudflared_ok
)
if exist "%~dp0tools\cloudflared.exe" (
  set "CLOUDFLARED_EXE=%~dp0tools\cloudflared.exe"
  goto cloudflared_ok
)

echo [WARN] cloudflared not found. Trying winget install ...
where winget >nul 2>nul
if not "%errorlevel%"=="0" goto cloudflared_missing
winget install -e --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements
where cloudflared >nul 2>nul
if "%errorlevel%"=="0" (
  set "CLOUDFLARED_EXE=cloudflared"
  goto cloudflared_ok
)
if exist "%ProgramFiles%\cloudflared\cloudflared.exe" (
  set "CLOUDFLARED_EXE=%ProgramFiles%\cloudflared\cloudflared.exe"
  goto cloudflared_ok
)

:cloudflared_missing
echo [ERROR] cloudflared is required but not installed.
echo [HINT] Install one of the following then re-run this script:
echo        winget install -e --id Cloudflare.cloudflared
echo        https://github.com/cloudflare/cloudflared/releases
goto failed

:cloudflared_ok
echo [2/3] Detecting backend status ...
set "BACKEND_SCHEME=NONE"
where curl.exe >nul 2>nul
if "%errorlevel%"=="0" (
  curl.exe -sS -o nul --noproxy "*" --max-time 2 "%HEALTH_URL_HTTP%" >nul 2>nul
  if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTP"
  if /I "!BACKEND_SCHEME!"=="NONE" (
    curl.exe -k -sS -o nul --noproxy "*" --max-time 2 "%HEALTH_URL_HTTPS%" >nul 2>nul
    if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTPS"
  )
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%HEALTH_URL_HTTP%' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }"
  if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTP"
  if /I "!BACKEND_SCHEME!"=="NONE" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }; Invoke-WebRequest -Uri '%HEALTH_URL_HTTPS%' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }"
    if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTPS"
  )
)
if /I "%BACKEND_SCHEME%"=="HTTP" goto backend_ready
if /I "%BACKEND_SCHEME%"=="HTTPS" goto backend_ready

echo [2/3] Starting backend in another window ...
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if($p){$p | ForEach-Object { Write-Output $_ }}"') do (
  taskkill /F /PID %%P >nul 2>nul
)
start "TYXT Backend" cmd /k set TYXT_NO_BROWSER=1^& call "%~dp0start_agent.bat"

echo [2/3] Waiting backend health ...
set /a TRY=0
:wait_loop
set /a TRY+=1
set "BACKEND_SCHEME=NONE"
where curl.exe >nul 2>nul
if "%errorlevel%"=="0" (
  curl.exe -sS -o nul --noproxy "*" --max-time 2 "%HEALTH_URL_HTTP%" >nul 2>nul
  if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTP"
  if /I "!BACKEND_SCHEME!"=="NONE" (
    curl.exe -k -sS -o nul --noproxy "*" --max-time 2 "%HEALTH_URL_HTTPS%" >nul 2>nul
    if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTPS"
  )
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%HEALTH_URL_HTTP%' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }"
  if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTP"
  if /I "!BACKEND_SCHEME!"=="NONE" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }; Invoke-WebRequest -Uri '%HEALTH_URL_HTTPS%' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }"
    if "!errorlevel!"=="0" set "BACKEND_SCHEME=HTTPS"
  )
)
if /I "!BACKEND_SCHEME!"=="HTTP" goto backend_ready
if /I "!BACKEND_SCHEME!"=="HTTPS" goto backend_ready
if !TRY! GEQ 300 (
  echo [ERROR] Backend health check timeout.
  echo [HINT] Check logs in the backend window.
  echo [HINT] Test manually:
  echo [HINT]   curl.exe -i --noproxy "*" http://127.0.0.1:5000/health
  echo [HINT]   curl.exe -k -i --noproxy "*" https://127.0.0.1:5000/health
  goto failed
)
if !TRY! EQU 30 echo [INFO] Still waiting... backend cold start can take around 1-2 minutes.
if !TRY! EQU 60 echo [INFO] Still waiting... if this keeps failing, check backend window for startup errors.
if !TRY! EQU 90 echo [INFO] Still waiting... verify Python/.venv deps were installed successfully.
timeout /t 1 /nobreak >nul
goto wait_loop

:backend_ready
if /I "%BACKEND_SCHEME%"=="HTTPS" (
  set "BACKEND_BASE=%BACKEND_BASE_HTTPS%"
  set "TUNNEL_TLS_ARGS=--no-tls-verify"
  echo [OK] Backend is ready. HTTPS origin detected.
  echo [INFO] Local browser: https://127.0.0.1:5000/
) else (
  set "BACKEND_BASE=%BACKEND_BASE_HTTP%"
  set "TUNNEL_TLS_ARGS="
  echo [OK] Backend is ready. HTTP origin detected.
  echo [INFO] Local browser: http://127.0.0.1:5000/
)

echo [3/3] Starting quick tunnel ...
echo [INFO] Keep this window open while remote users are using the service.
echo [INFO] Press Ctrl+C to stop tunnel.
echo [INFO] Tunnel target: %BACKEND_BASE%
echo [INFO] Mobile frontend path: /mobile/ (append to the trycloudflare URL)
if not "%TUNNEL_TLS_ARGS%"=="" echo [INFO] Tunnel origin args: %TUNNEL_TLS_ARGS%
set "CF_EDGE_ARGS=--protocol http2 --edge-ip-version 4"
echo [INFO] Tunnel edge args: %CF_EDGE_ARGS%
echo [INFO] Auto reconnect: ON (delay=%CF_RETRY_DELAY_SEC%s, max_retries=%CF_RETRY_MAX%, 0 means infinite)
echo.

set "TUNNEL_URL="
:tunnel_loop
set /a CF_RETRY_COUNT+=1
if not "%CF_RETRY_MAX%"=="0" (
  if !CF_RETRY_COUNT! GTR %CF_RETRY_MAX% (
    set "SCRIPT_RC=1"
    echo [ERROR] Tunnel retry reached max limit: %CF_RETRY_MAX%.
    echo [HINT] Check DNS/firewall and set system DNS to 223.5.5.5 / 119.29.29.29, then rerun.
    goto tunnel_stopped
  )
)
echo [INFO] Tunnel attempt !CF_RETRY_COUNT! ...
"%CLOUDFLARED_EXE%" tunnel --url %BACKEND_BASE% %TUNNEL_TLS_ARGS% %CF_EDGE_ARGS% --no-autoupdate
set "CF_RC=!errorlevel!"
if "!CF_RC!"=="0" goto tunnel_stopped

echo [WARN] cloudflared exited with code !CF_RC!.
echo [INFO] Retrying once with default protocol settings...
"%CLOUDFLARED_EXE%" tunnel --url %BACKEND_BASE% %TUNNEL_TLS_ARGS% --no-autoupdate
set "CF_RC=!errorlevel!"
if "!CF_RC!"=="0" goto tunnel_stopped

if "!CF_HOSTS_FALLBACK_DONE!"=="0" (
  echo [WARN] cloudflared retry also failed with code !CF_RC!.
  echo [INFO] Trying DNS hosts fallback for region1.v2.argotunnel.com ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$target='region1.v2.argotunnel.com'; $servers=@('223.5.5.5','119.29.29.29','1.1.1.1'); $ip=$null; foreach($s in $servers){ try{ $ip=(Resolve-DnsName -Name $target -Server $s -Type A -ErrorAction Stop | Select-Object -First 1 -ExpandProperty IPAddress); if($ip){break} } catch {} }; if(-not $ip){ exit 1 }; $hosts=Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'; $lines=@(); if(Test-Path $hosts){ $lines=Get-Content $hosts -ErrorAction SilentlyContinue | Where-Object { $_ -notmatch '(^|\\s)region1\\.v2\\.argotunnel\\.com(\\s|$)' } }; $lines += ($ip + ' region1.v2.argotunnel.com'); Set-Content -Path $hosts -Value $lines -Encoding ASCII; Write-Output ('[OK] Hosts fallback applied: region1.v2.argotunnel.com -> ' + $ip); exit 0"
  if "!errorlevel!"=="0" (
    set "CF_HOSTS_FALLBACK_DONE=1"
    echo [INFO] Hosts fallback applied. Continue auto reconnect.
  ) else (
    echo [WARN] Hosts fallback failed (may require Administrator privileges).
  )
)

echo [INFO] Waiting %CF_RETRY_DELAY_SEC%s before reconnect...
timeout /t %CF_RETRY_DELAY_SEC% /nobreak >nul
goto tunnel_loop

:tunnel_stopped

echo.
echo [INFO] Tunnel stopped.
echo [TIP] If backend is still running, use stop_all.bat to stop quickly.
goto done

:failed
set "SCRIPT_RC=1"
echo.
echo [FAILED] start_remote_easy.bat did not finish successfully.
echo [HINT] Run setup_start_cn.bat first if dependencies are missing.

:done
echo.
pause
exit /b %SCRIPT_RC%
