@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT LAN Client Join (Zero Input)
cd /d "%~dp0"

set "TYXT_ZERO_BAT_VERSION=20260302.7"
set "SERVER_IP=127.0.0.1"
set "SERVER_PORT=5000"
set "SERVER_DOMAIN="
set "PS_CMD=powershell -NoProfile -ExecutionPolicy Bypass"
set "CURL_CMD=%SystemRoot%\System32\curl.exe"
set "TMP_TOOLS_DIR=%TEMP%\tyxt_lan_client_tools"
set "ROOT_CA_FILE=%TMP_TOOLS_DIR%\rootCA.cer"

echo.
echo ==========================================
echo   TYXT LAN Client Join (Zero Input)
echo ==========================================
echo.
echo [INFO] zero-input version: %TYXT_ZERO_BAT_VERSION%
echo [INFO] script path: %~f0
echo [INFO] fixed server ip: %SERVER_IP%
if not "%SERVER_DOMAIN%"=="" echo [INFO] fixed server domain: %SERVER_DOMAIN%

if not exist "%TMP_TOOLS_DIR%" mkdir "%TMP_TOOLS_DIR%" >nul 2>nul
if not exist "%CURL_CMD%" set "CURL_CMD=curl.exe"

echo [INFO] Checking server connectivity...
%PS_CMD% -Command "$ip='%SERVER_IP%';$port=%SERVER_PORT%;$ok=$false;try{$c=New-Object System.Net.Sockets.TcpClient;$ar=$c.BeginConnect($ip,$port,$null,$null);if($ar.AsyncWaitHandle.WaitOne(1200,$false) -and $c.Connected){$ok=$true};$c.Close()}catch{};if($ok){exit 0}else{exit 9}"
if errorlevel 1 (
  echo.
  echo [ERROR] Server not reachable on %SERVER_IP%:%SERVER_PORT%.
  echo [ERROR] Please ensure backend is running and firewall allows LAN access.
  pause >nul
  exit /b 1
)

echo [INFO] Downloading root CA from server...
set "DL_OK=0"
"%CURL_CMD%" --version >nul 2>nul
if not errorlevel 1 (
  if not "%SERVER_DOMAIN%"=="" (
    "%CURL_CMD%" -k -f -L --max-time 8 -o "%ROOT_CA_FILE%" "https://%SERVER_DOMAIN%:%SERVER_PORT%/tools/lan/rootca" >nul 2>nul
    if not errorlevel 1 if exist "%ROOT_CA_FILE%" set "DL_OK=1"
  )
  if "!DL_OK!"=="0" (
    "%CURL_CMD%" -k -f -L --max-time 8 -o "%ROOT_CA_FILE%" "https://%SERVER_IP%:%SERVER_PORT%/tools/lan/rootca" >nul 2>nul
    if not errorlevel 1 if exist "%ROOT_CA_FILE%" set "DL_OK=1"
  )
  if "!DL_OK!"=="0" (
    "%CURL_CMD%" -f -L --max-time 8 -o "%ROOT_CA_FILE%" "http://%SERVER_IP%:%SERVER_PORT%/tools/lan/rootca" >nul 2>nul
    if not errorlevel 1 if exist "%ROOT_CA_FILE%" set "DL_OK=1"
  )
) else (
  %PS_CMD% -Command "$ErrorActionPreference='SilentlyContinue';try{[System.Net.ServicePointManager]::SecurityProtocol=[System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls11 -bor [System.Net.SecurityProtocolType]::Tls}catch{};try{[System.Net.ServicePointManager]::ServerCertificateValidationCallback={ $true }}catch{};$ip='%SERVER_IP%';$port=%SERVER_PORT%;$domain='%SERVER_DOMAIN%';$out='%ROOT_CA_FILE%';$bases=New-Object System.Collections.Generic.List[string];if($domain){$bases.Add('https://'+$domain+':'+$port)};$bases.Add('https://'+$ip+':'+$port);$bases.Add('http://'+$ip+':'+$port);$ok=$false;foreach($b in $bases){try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri ($b+'/tools/lan/rootca') -OutFile $out;if(Test-Path -LiteralPath $out){$ok=$true;break}}catch{}};if($ok){exit 0}else{exit 7}"
  if not errorlevel 1 if exist "%ROOT_CA_FILE%" set "DL_OK=1"
)
if "!DL_OK!"=="0" (
  echo.
  echo [ERROR] Failed to download root CA from server.
  echo [ERROR] Please check LAN connectivity and server route /tools/lan/rootca.
  pause >nul
  exit /b 1
)
if not exist "%ROOT_CA_FILE%" (
  echo.
  echo [ERROR] rootCA.cer missing after download.
  pause >nul
  exit /b 1
)

echo [INFO] Importing root CA to current user trust store...
%PS_CMD% -Command "$p='%ROOT_CA_FILE%';$ok=$false;try{Import-Certificate -FilePath $p -CertStoreLocation 'Cert:\CurrentUser\Root' -ErrorAction Stop | Out-Null;$ok=$true}catch{};if(-not $ok){try{certutil -user -addstore root $p | Out-Null;$ok=$true}catch{}};if($ok){exit 0}else{exit 8}"
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to import root CA.
  echo [ERROR] Try running as a normal user with cert store access, or import manually.
  pause >nul
  exit /b 1
)

echo [INFO] Opening TYXT UI...
start "" "https://%SERVER_IP%:%SERVER_PORT%/"
echo [OK] Completed. Browser should open shortly.
endlocal
exit /b 0
