@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT LAN Client Join
cd /d "%~dp0"

set "SERVER_IP=%~1"
set "PS_CMD=powershell -NoProfile -ExecutionPolicy Bypass"
set "LOCAL_JOIN_PS1=%~dp0tools\join_lan_ui.ps1"
set "LOCAL_INSTALL_PS1=%~dp0tools\install_lan_root_ca.ps1"
set "RUNTIME_JOIN_PS1=%LOCAL_JOIN_PS1%"
set "TMP_TOOLS_DIR=%TEMP%\tyxt_lan_client_tools"
set "RUNTIME_INSTALL_PS1=%TMP_TOOLS_DIR%\install_lan_root_ca.ps1"
set "USE_LOCAL_SCRIPTS=0"
set "LOCAL_GATEWAY="
set "LOCAL_IP="

echo.
echo ==========================================
echo   TYXT LAN Client Join
echo ==========================================
echo.
echo [INFO] script path: %~f0
echo [INFO] client_join_lan_ui.bat version: 20260302.6
for /f "usebackq delims=" %%i in (`%PS_CMD% -Command "$gw='';try{$gw=(Get-NetIPConfiguration ^| ? {$_.IPv4DefaultGateway -and $_.IPv4Address} ^| select -first 1).IPv4DefaultGateway.NextHop}catch{}; if(-not $gw){try{$gw=(Get-CimInstance Win32_NetworkAdapterConfiguration ^| ? {$_.IPEnabled -eq $true -and $_.DefaultIPGateway} ^| select -first 1).DefaultIPGateway[0]}catch{}}; if($gw){$gw}"`) do set "LOCAL_GATEWAY=%%i"
for /f "usebackq delims=" %%i in (`%PS_CMD% -Command "$ip='';try{$ip=(Get-NetIPAddress -AddressFamily IPv4 ^| ? {$_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown'} ^| select -first 1 -ExpandProperty IPAddress)}catch{}; if($ip){$ip}"`) do set "LOCAL_IP=%%i"
if defined LOCAL_IP echo [INFO] local client IP: %LOCAL_IP%
if defined LOCAL_GATEWAY echo [INFO] local gateway  : %LOCAL_GATEWAY%
echo [INFO] Auto mode: server IP will be discovered automatically.

if exist "%LOCAL_JOIN_PS1%" if exist "%LOCAL_INSTALL_PS1%" set "USE_LOCAL_SCRIPTS=1"

if "%USE_LOCAL_SCRIPTS%"=="1" (
  echo [INFO] Using local client scripts.
) else (
  if "%SERVER_IP%"=="" (
    echo [INFO] Auto discovering server IP for script download...
    for /f "usebackq delims=" %%i in (`%PS_CMD% -Command "$ErrorActionPreference='SilentlyContinue';try{[System.Net.ServicePointManager]::SecurityProtocol=[System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls11 -bor [System.Net.SecurityProtocolType]::Tls}catch{};try{[System.Net.ServicePointManager]::ServerCertificateValidationCallback={ $true }}catch{};$seen=@{};$cands=New-Object System.Collections.Generic.List[string];function addip([string]$x){if([string]::IsNullOrWhiteSpace($x)){return};$x=$x.Trim();if($x -notmatch '^\d{1,3}(\.\d{1,3}){3}$'){return};if($x -like '127.*'){return};if($seen.ContainsKey($x)){return};$seen[$x]=$true;[void]$cands.Add($x)};$locals=New-Object System.Collections.Generic.List[string];try{$nics=[System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces();foreach($ni in $nics){if($ni.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up){continue};$p=$ni.GetIPProperties();foreach($u in $p.UnicastAddresses){if($u.Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork){continue};$lip=$u.Address.ToString();if($lip -like '127.*'){continue};if(-not $locals.Contains($lip)){[void]$locals.Add($lip)}};foreach($g in $p.GatewayAddresses){$gw=$g.Address.ToString();if($gw -match '^\d{1,3}(\.\d{1,3}){3}$' -and $gw -ne '0.0.0.0'){addip $gw}}}}catch{};try{$arp=arp -a}catch{$arp=@()};foreach($ln in $arp){if($ln -match '^\s*(\d+\.\d+\.\d+\.\d+)\s+[0-9a-fA-F\-]{11,17}\s+\w+'){addip $matches[1]}};foreach($lip in $locals){if($lip -match '^(\d+\.\d+\.\d+)\.\d+$'){$pre=$matches[1];for($n=2;$n -le 254;$n++){$ip=$pre+'.'+$n;if($ip -ne $lip){addip $ip}}}};foreach($ip in $cands){$open=$false;try{$c=New-Object System.Net.Sockets.TcpClient;$ar=$c.BeginConnect($ip,5000,$null,$null);if($ar.AsyncWaitHandle.WaitOne(120,$false) -and $c.Connected){$open=$true};$c.Close()}catch{};if(-not $open){continue};foreach($sch in @('https','http')){try{$u=$sch+'://'+$ip+':5000/tools/lan/bootstrap';$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $u;if($r.StatusCode -ge 200 -and $r.Content -match 'preferred_domain'){Write-Output $ip;exit 0}}catch{}}};exit 0"`) do (
      if not defined SERVER_IP set "SERVER_IP=%%i"
    )
  )
  if "%SERVER_IP%"=="" (
    echo.
    echo [WARN] Auto-discovery failed in this LAN.
    echo [ERROR] Zero-input mode cannot continue without discovery.
    echo [ERROR] Use pre-generated zero-input file from server:
    echo [ERROR]   client_join_lan_ui_zero_input.bat
    pause >nul
    exit /b 1
  )

  if not exist "%TMP_TOOLS_DIR%" mkdir "%TMP_TOOLS_DIR%" >nul 2>nul
  set "RUNTIME_JOIN_PS1=%TMP_TOOLS_DIR%\join_lan_ui.ps1"
  set "RUNTIME_INSTALL_PS1=%TMP_TOOLS_DIR%\install_lan_root_ca.ps1"

  echo [INFO] Local scripts not found. Downloading from server...
  set "DL_OK=0"
  set "CURL_BIN=%SystemRoot%\System32\curl.exe"
  if not exist "!CURL_BIN!" set "CURL_BIN=curl.exe"
  "!CURL_BIN!" --version >nul 2>nul
  if not errorlevel 1 (
    "!CURL_BIN!" -k -f -L --max-time 8 -o "%RUNTIME_JOIN_PS1%" "https://%SERVER_IP%:5000/tools/lan/client_join_ps1" >nul 2>nul
    if not errorlevel 1 (
      "!CURL_BIN!" -k -f -L --max-time 8 -o "%RUNTIME_INSTALL_PS1%" "https://%SERVER_IP%:5000/tools/lan/install_lan_root_ca_ps1" >nul 2>nul
      if not errorlevel 1 set "DL_OK=1"
    )
    if "!DL_OK!"=="0" (
      "!CURL_BIN!" -f -L --max-time 8 -o "%RUNTIME_JOIN_PS1%" "http://%SERVER_IP%:5000/tools/lan/client_join_ps1" >nul 2>nul
      if not errorlevel 1 (
        "!CURL_BIN!" -f -L --max-time 8 -o "%RUNTIME_INSTALL_PS1%" "http://%SERVER_IP%:5000/tools/lan/install_lan_root_ca_ps1" >nul 2>nul
        if not errorlevel 1 set "DL_OK=1"
      )
    )
  )
  if "!DL_OK!"=="0" (
    %PS_CMD% -Command "$ErrorActionPreference='Stop';$ip='%SERVER_IP%';$port=5000;$outDir='%TMP_TOOLS_DIR%';New-Item -ItemType Directory -Force -Path $outDir | Out-Null;try{[System.Net.ServicePointManager]::SecurityProtocol=[System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls11 -bor [System.Net.SecurityProtocolType]::Tls}catch{};try{[System.Net.ServicePointManager]::ServerCertificateValidationCallback={ $true }}catch{};$bases=@('https://'+$ip+':'+$port,'http://'+$ip+':'+$port);$ok=$false;foreach($b in $bases){try{Invoke-WebRequest -UseBasicParsing -Uri ($b+'/tools/lan/client_join_ps1') -OutFile (Join-Path $outDir 'join_lan_ui.ps1');Invoke-WebRequest -UseBasicParsing -Uri ($b+'/tools/lan/install_lan_root_ca_ps1') -OutFile (Join-Path $outDir 'install_lan_root_ca.ps1');$ok=$true;break}catch{}};if(-not $ok){exit 7};exit 0"
    if not errorlevel 1 set "DL_OK=1"
  )
  if "!DL_OK!"=="0" (
    echo.
    echo [ERROR] Failed to download client scripts from server.
    echo [ERROR] Please check server IP / backend status and retry.
    pause >nul
    exit /b 1
  )
  if not exist "%RUNTIME_JOIN_PS1%" (
    echo.
    echo [ERROR] Downloaded join script is missing.
    pause >nul
    exit /b 1
  )
  if not exist "%RUNTIME_INSTALL_PS1%" (
    echo.
    echo [ERROR] Downloaded install script is missing.
    pause >nul
    exit /b 1
  )
  echo [INFO] Download completed.
)

if "%SERVER_IP%"=="" (
  %PS_CMD% -File "%RUNTIME_JOIN_PS1%"
) else (
  %PS_CMD% -File "%RUNTIME_JOIN_PS1%" -ServerIp "%SERVER_IP%"
)

if errorlevel 1 (
  echo.
  echo [ERROR] Client setup failed. Press any key to exit.
  pause >nul
  exit /b 1
)

endlocal
exit /b 0
