[CmdletBinding()]
param(
  [string]$ProjectRoot = "",
  [string[]]$ExtraNames = @(),
  [string]$PreferredDomain = "",
  [switch]$SkipHosts,
  [switch]$AutoInstallMkcert
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
  param([string]$InputRoot)
  if ($InputRoot -and (Test-Path -LiteralPath $InputRoot)) {
    return (Resolve-Path -LiteralPath $InputRoot).Path
  }
  return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Test-IsAdmin {
  try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = [Security.Principal.WindowsPrincipal]::new($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch {
    return $false
  }
}

function Get-MkcertExe {
  if ($env:TYXT_MKCERT -and (Test-Path -LiteralPath $env:TYXT_MKCERT)) {
    return (Resolve-Path -LiteralPath $env:TYXT_MKCERT).Path
  }

  $candidates = @(
    (Join-Path $PSScriptRoot "mkcert\mkcert.exe"),
    (Join-Path (Join-Path $PSScriptRoot "..") "tools\mkcert\mkcert.exe")
  )
  foreach ($c in $candidates) {
    if (Test-Path -LiteralPath $c) {
      return (Resolve-Path -LiteralPath $c).Path
    }
  }

  try {
    $cmd = Get-Command mkcert.exe -ErrorAction Stop
    if ($cmd -and $cmd.Source) {
      return $cmd.Source
    }
  } catch {
  }
  return ""
}

function Try-AutoInstallMkcert {
  if (Get-MkcertExe) { return $true }

  Write-Host "[INFO] mkcert not found. Trying automatic install..." -ForegroundColor Yellow

  function Show-InstallLogTail {
    param(
      [string]$LogPath,
      [string]$Title
    )
    if (-not (Test-Path -LiteralPath $LogPath)) { return }
    Write-Host "[WARN] $Title (tail log):" -ForegroundColor Yellow
    try {
      Get-Content -LiteralPath $LogPath -Tail 20 | ForEach-Object { Write-Host ("  " + $_) }
    } catch {
    }
  }

  function Remove-InstallLog {
    param([string]$LogPath)
    try {
      if (Test-Path -LiteralPath $LogPath) {
        Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
      }
    } catch {
    }
  }

  try {
    $wg = Get-Command winget.exe -ErrorAction Stop
    if ($wg) {
      Write-Host "[INFO] Installing mkcert via winget (quiet mode)..." -ForegroundColor Cyan
      $wgLog = Join-Path $env:TEMP ("tyxt_mkcert_winget_" + [Guid]::NewGuid().ToString("N") + ".log")
      & winget install --id FiloSottile.mkcert -e --accept-package-agreements --accept-source-agreements --silent --disable-interactivity *> $wgLog
      $wgCode = $LASTEXITCODE
      if (Get-MkcertExe) {
        Remove-InstallLog -LogPath $wgLog
        return $true
      }
      Show-InstallLogTail -LogPath $wgLog -Title ("winget install mkcert failed (exit=" + $wgCode + ")")
      Remove-InstallLog -LogPath $wgLog
    }
  } catch {
  }

  try {
    $cc = Get-Command choco.exe -ErrorAction Stop
    if ($cc) {
      Write-Host "[INFO] Installing mkcert via choco (quiet mode)..." -ForegroundColor Cyan
      $ccLog = Join-Path $env:TEMP ("tyxt_mkcert_choco_" + [Guid]::NewGuid().ToString("N") + ".log")
      & choco install mkcert -y --no-progress *> $ccLog
      $ccCode = $LASTEXITCODE
      if (Get-MkcertExe) {
        Remove-InstallLog -LogPath $ccLog
        return $true
      }
      Show-InstallLogTail -LogPath $ccLog -Title ("choco install mkcert failed (exit=" + $ccCode + ")")
      Remove-InstallLog -LogPath $ccLog
    }
  } catch {
  }

  return [bool](Get-MkcertExe)
}

function Add-UniqueName {
  param(
    [System.Collections.Generic.List[string]]$Names,
    [string]$Name
  )
  $n = [string]$Name
  if ([string]::IsNullOrWhiteSpace($n)) { return }
  $n = $n.Trim()
  if (-not $Names.Contains($n)) {
    [void]$Names.Add($n)
  }
}

function Test-IsPrivateIpv4 {
  param([string]$Ip)
  if ([string]::IsNullOrWhiteSpace($Ip)) { return $false }
  $x = $Ip.Trim()
  if ($x -match "^10\.") { return $true }
  if ($x -match "^192\.168\.") { return $true }
  if ($x -match "^172\.(1[6-9]|2[0-9]|3[0-1])\.") { return $true }
  return $false
}

function Get-NetworkProfile {
  $ips = [System.Collections.Generic.List[string]]::new()
  $gateway = ""
  $primaryIp = ""
  $ifAlias = ""

  try {
    $cfgs = Get-NetIPConfiguration -ErrorAction Stop | Where-Object {
      $_.IPv4Address -and $_.IPv4DefaultGateway
    }
    $ordered = @(
      $cfgs | Sort-Object `
        @{ Expression = { if (Test-IsPrivateIpv4 -Ip ([string]$_.IPv4Address.IPAddress)) { 0 } else { 1 } } }, `
        @{ Expression = { if (([string]$_.InterfaceAlias) -match "Wi-?Fi|WLAN|Ethernet|以太网") { 0 } else { 1 } } }
    )
    $first = $ordered | Select-Object -First 1
    if ($first) {
      $primaryIp = [string]$first.IPv4Address.IPAddress
      $gateway = [string]$first.IPv4DefaultGateway.NextHop
      $ifAlias = [string]$first.InterfaceAlias
    }
  } catch {
  }

  try {
    $all = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {
      $_.IPAddress -and
      $_.IPAddress -notmatch "^127\." -and
      $_.IPAddress -ne "0.0.0.0" -and
      $_.PrefixOrigin -ne "WellKnown" -and
      $_.IPAddress -notmatch "^169\.254\."
    } | Select-Object -ExpandProperty IPAddress -Unique
    foreach ($ip in $all) {
      Add-UniqueName -Names $ips -Name $ip
    }
  } catch {
  }

  if ($primaryIp) {
    $tmp = [System.Collections.Generic.List[string]]::new()
    Add-UniqueName -Names $tmp -Name $primaryIp
    foreach ($x in $ips) { Add-UniqueName -Names $tmp -Name $x }
    $ips = $tmp
  }

  return @{
    primary_ip = $primaryIp
    default_gateway = $gateway
    interface_alias = $ifAlias
    ips = @($ips.ToArray())
  }
}

function Normalize-HostLabel {
  param([string]$Raw)
  $s = [string]$Raw
  if ([string]::IsNullOrWhiteSpace($s)) { return "" }
  $s = $s.Trim().ToLowerInvariant()
  $s = [regex]::Replace($s, "[^a-z0-9-]", "-")
  $s = [regex]::Replace($s, "-{2,}", "-").Trim("-")
  if (-not $s) { return "" }
  return $s
}

function Ensure-HostsEntry {
  param(
    [string]$Ip,
    [string]$Domain
  )
  if ([string]::IsNullOrWhiteSpace($Ip) -or [string]::IsNullOrWhiteSpace($Domain)) {
    return $false
  }
  if (-not (Test-IsAdmin)) {
    Write-Host "[WARN] Not admin. Skip hosts file update for $Domain." -ForegroundColor Yellow
    return $false
  }
  $hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
  $marker = "# TYXT_LAN_HTTPS"
  $domainEsc = [regex]::Escape($Domain)
  $lines = @()
  if (Test-Path -LiteralPath $hostsPath) {
    $lines = Get-Content -LiteralPath $hostsPath -ErrorAction SilentlyContinue
  }
  $filtered = foreach ($ln in $lines) {
    if ($ln -match $marker) { continue }
    if ($ln -match "^\s*\d+\.\d+\.\d+\.\d+\s+$domainEsc(\s+|$)") { continue }
    $ln
  }
  $entry = "$Ip`t$Domain`t$marker"
  $filtered + $entry | Set-Content -LiteralPath $hostsPath -Encoding ascii
  return $true
}

function Ensure-FirewallInboundRule {
  param(
    [int]$Port = 5000,
    [string]$RuleName = "TYXT LAN HTTPS 5000"
  )
  if (-not (Test-IsAdmin)) {
    Write-Host "[WARN] Not admin. Skip firewall rule setup for TCP $Port." -ForegroundColor Yellow
    return $false
  }
  try {
    $existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($existing) {
      Set-NetFirewallRule -DisplayName $RuleName -Enabled True -Direction Inbound -Action Allow -Profile Private,Domain -ErrorAction SilentlyContinue | Out-Null
      return $true
    }
  } catch {
  }
  try {
    netsh advfirewall firewall add rule name="$RuleName" dir=in action=allow protocol=TCP localport=$Port profile=private,domain | Out-Null
    return $true
  } catch {
  }
  return $false
}

function Write-ZeroInputClientBat {
  param(
    [string]$ProjectRootPath,
    [string]$ServerIp,
    [int]$ServerPort,
    [string]$ServerDomain
  )
  if ([string]::IsNullOrWhiteSpace($ProjectRootPath)) { return "" }
  if ([string]::IsNullOrWhiteSpace($ServerIp)) { return "" }

  $batPath = Join-Path $ProjectRootPath "client_join_lan_ui_zero_input.bat"
  $ipSafe = $ServerIp.Trim()
  $domainSafe = [string]$ServerDomain
  if ($domainSafe) { $domainSafe = $domainSafe.Trim() }
  $portSafe = [int]$ServerPort
  if ($portSafe -le 0) { $portSafe = 5000 }

  $batTemplate = @'
@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT LAN Client Join (Zero Input)
cd /d "%~dp0"

set "TYXT_ZERO_BAT_VERSION=20260302.7"
set "SERVER_IP=__SERVER_IP__"
set "SERVER_PORT=__SERVER_PORT__"
set "SERVER_DOMAIN=__SERVER_DOMAIN__"
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
'@

  $bat = $batTemplate.
    Replace("__SERVER_IP__", $ipSafe).
    Replace("__SERVER_PORT__", [string]$portSafe).
    Replace("__SERVER_DOMAIN__", $domainSafe)

  Set-Content -LiteralPath $batPath -Value $bat -Encoding ascii
  return $batPath
}

$root = Resolve-ProjectRoot -InputRoot $ProjectRoot

if ($AutoInstallMkcert) {
  [void](Try-AutoInstallMkcert)
}

$mkcertExe = Get-MkcertExe
if (-not $mkcertExe) {
  Write-Host "[ERROR] mkcert not found." -ForegroundColor Red
  Write-Host "Install mkcert first (Windows examples):"
  Write-Host "  winget install FiloSottile.mkcert"
  Write-Host "  choco install mkcert"
  Write-Host "Or set env: TYXT_MKCERT=<full_path_to_mkcert.exe>"
  exit 1
}

$net = Get-NetworkProfile
$primaryIp = [string]$net.primary_ip
$gateway = [string]$net.default_gateway
$ips = @($net.ips)

$hostBase = Normalize-HostLabel -Raw $env:COMPUTERNAME
if (-not $hostBase) { $hostBase = "tyxt-node" }
$domain = [string]$PreferredDomain
if ([string]::IsNullOrWhiteSpace($domain)) {
  $domain = "tyxt-$hostBase.local"
}
$domain = $domain.Trim().ToLowerInvariant()

$certDir = Join-Path $root "certs\lan"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

$certFile = Join-Path $certDir "server.pem"
$keyFile = Join-Path $certDir "server-key.pem"
$rootPemOut = Join-Path $certDir "rootCA.pem"
$rootCerOut = Join-Path $certDir "rootCA.cer"
$bootstrapOut = Join-Path $certDir "lan_bootstrap.json"

Write-Host "[1/5] Installing local CA on server..." -ForegroundColor Cyan
& $mkcertExe -install
if ($LASTEXITCODE -ne 0) {
  Write-Host "[ERROR] mkcert -install failed (exit=$LASTEXITCODE)." -ForegroundColor Red
  exit 5
}

$names = [System.Collections.Generic.List[string]]::new()
Add-UniqueName -Names $names -Name "localhost"
Add-UniqueName -Names $names -Name "127.0.0.1"
Add-UniqueName -Names $names -Name "::1"
Add-UniqueName -Names $names -Name $env:COMPUTERNAME
Add-UniqueName -Names $names -Name $domain
foreach ($ip in $ips) { Add-UniqueName -Names $names -Name $ip }
foreach ($x in $ExtraNames) { Add-UniqueName -Names $names -Name $x }

if ($names.Count -le 0) {
  Write-Host "[ERROR] No SAN names prepared for certificate." -ForegroundColor Red
  exit 2
}

Write-Host "[2/5] Generating LAN certificate..." -ForegroundColor Cyan
Write-Host ("SAN names: " + (($names.ToArray()) -join ", "))
& $mkcertExe -cert-file $certFile -key-file $keyFile @($names.ToArray())
if ($LASTEXITCODE -ne 0) {
  Write-Host "[ERROR] mkcert certificate generation failed (exit=$LASTEXITCODE)." -ForegroundColor Red
  exit 6
}

Write-Host "[3/5] Exporting root CA for clients..." -ForegroundColor Cyan
$caroot = (& $mkcertExe -CAROOT).Trim()
if (-not $caroot) {
  Write-Host "[ERROR] mkcert -CAROOT returned empty." -ForegroundColor Red
  exit 3
}
$rootPem = Join-Path $caroot "rootCA.pem"
if (-not (Test-Path -LiteralPath $rootPem)) {
  Write-Host "[ERROR] rootCA.pem not found in CAROOT: $caroot" -ForegroundColor Red
  exit 4
}
Copy-Item -LiteralPath $rootPem -Destination $rootPemOut -Force
Copy-Item -LiteralPath $rootPem -Destination $rootCerOut -Force

Write-Host "[4/5] Writing bootstrap info..." -ForegroundColor Cyan
$bootstrap = [ordered]@{
  schema_version = 1
  generated_at = (Get-Date).ToString("s")
  server_host = [string]$env:COMPUTERNAME
  preferred_domain = $domain
  primary_ipv4 = $primaryIp
  default_gateway = $gateway
  interface_alias = [string]$net.interface_alias
  port = 5000
  https_url_ip = $(if ($primaryIp) { "https://$primaryIp:5000/" } else { "" })
  https_url_domain = $(if ($domain) { "https://$domain:5000/" } else { "" })
  san_names = @($names.ToArray())
}
$bootstrap | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $bootstrapOut -Encoding UTF8

$zeroClientBat = Write-ZeroInputClientBat `
  -ProjectRootPath $root `
  -ServerIp $primaryIp `
  -ServerPort 5000 `
  -ServerDomain $domain

Write-Host "[5/5] Updating hosts entry for server custom domain..." -ForegroundColor Cyan
$hostsUpdated = $false
if (-not $SkipHosts) {
  $hostsUpdated = Ensure-HostsEntry -Ip $primaryIp -Domain $domain
}
$firewallReady = Ensure-FirewallInboundRule -Port 5000 -RuleName "TYXT LAN HTTPS 5000"

Write-Host ""
Write-Host "LAN HTTPS setup completed." -ForegroundColor Green
Write-Host "Server IP      : $primaryIp"
Write-Host "Gateway        : $gateway"
Write-Host "Custom domain  : $domain"
Write-Host ("Hosts updated  : " + ($(if ($hostsUpdated) { "yes" } else { "no" })))
Write-Host ("Firewall rule  : " + ($(if ($firewallReady) { "yes" } else { "no" })))
Write-Host ""
Write-Host "Generated files:"
Write-Host "  $certFile"
Write-Host "  $keyFile"
Write-Host "  $rootPemOut"
Write-Host "  $rootCerOut"
Write-Host "  $bootstrapOut"
if ($zeroClientBat) {
  Write-Host "  $zeroClientBat"
}
Write-Host ""
Write-Host "Next:"
Write-Host "1) Start backend with start_agent.bat or start_lan_https_easy.bat"
Write-Host "2) For absolute zero-input client setup, copy and run:"
if ($zeroClientBat) {
  Write-Host "   $zeroClientBat"
} else {
  Write-Host "   client_join_lan_ui.bat"
}
Write-Host "3) Access URL:"
if ($domain) {
  Write-Host "   https://${domain}:5000/"
}
if ($primaryIp) {
  Write-Host "   https://${primaryIp}:5000/"
}
