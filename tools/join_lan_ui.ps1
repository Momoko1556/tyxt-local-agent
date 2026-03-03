[CmdletBinding()]
param(
  [string]$ServerIp = "",
  [int]$ServerPort = 5000,
  [string]$BootstrapPath = "",
  [string]$RootCertPath = "",
  [switch]$SkipHosts,
  [switch]$NoOpen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = [Security.Principal.WindowsPrincipal]::new($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch {
    return $false
  }
}

function Resolve-ProjectRoot {
  return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Try-LoadJson {
  param([string]$Path)
  try {
    if ($Path -and (Test-Path -LiteralPath $Path)) {
      return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
    }
  } catch {
  }
  return $null
}

function Set-InsecureTlsForBootstrap {
  try {
    [System.Net.ServicePointManager]::SecurityProtocol = `
      [System.Net.SecurityProtocolType]::Tls12 -bor `
      [System.Net.SecurityProtocolType]::Tls11 -bor `
      [System.Net.SecurityProtocolType]::Tls
  } catch {
  }
  try {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
  } catch {
  }
}

function Download-FileInsecure {
  param(
    [string]$Url,
    [string]$OutFile
  )
  Set-InsecureTlsForBootstrap
  try {
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 10 | Out-Null
    return $true
  } catch {
    try {
      Invoke-WebRequest -Uri $Url -OutFile $OutFile -SkipCertificateCheck -TimeoutSec 10 | Out-Null
      return $true
    } catch {
      return $false
    }
  }
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
    Write-Host "[WARN] Not admin. Skip hosts update. Will use IP URL." -ForegroundColor Yellow
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

function Test-TcpPortOpen {
  param(
    [string]$Ip,
    [int]$Port = 5000,
    [int]$TimeoutMs = 180
  )
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $ar = $client.BeginConnect($Ip, $Port, $null, $null)
    $ok = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
    if ($ok -and $client.Connected) {
      try { $client.EndConnect($ar) } catch {}
      $client.Close()
      return $true
    }
    $client.Close()
  } catch {
  }
  return $false
}

function Try-FetchBootstrap {
  param(
    [string]$Ip,
    [int]$Port = 5000
  )
  $tmp = Join-Path $env:TEMP ("tyxt_probe_bootstrap_" + ($Ip -replace "\.", "_") + ".json")
  foreach ($scheme in @("https", "http")) {
    $url = "${scheme}://$Ip`:$Port/tools/lan/bootstrap"
    if (Download-FileInsecure -Url $url -OutFile $tmp) {
      $obj = Try-LoadJson -Path $tmp
      if ($obj) {
        return @{
          ok = $true
          bootstrap = $obj
          scheme = $scheme
        }
      }
    }
  }
  return @{
    ok = $false
    bootstrap = $null
    scheme = ""
  }
}

function Get-LanCandidateIps {
  param([string]$HintIp = "")
  $candidates = [System.Collections.Generic.List[string]]::new()
  $seen = @{}
  $localIps = [System.Collections.Generic.List[string]]::new()
  $prefixes = @{}

  function Add-Candidate {
    param([string]$Ip)
    $x = [string]$Ip
    if ([string]::IsNullOrWhiteSpace($x)) { return }
    $x = $x.Trim()
    if ($x -notmatch "^\d{1,3}(\.\d{1,3}){3}$") { return }
    if ($x -like "127.*") { return }
    if ($seen.ContainsKey($x)) { return }
    $seen[$x] = $true
    [void]$candidates.Add($x)
  }

  Add-Candidate -Ip $HintIp

  try {
    $cfgs = Get-NetIPConfiguration -ErrorAction Stop | Where-Object {
      $_.IPv4Address
    }
    foreach ($cfg in $cfgs) {
      $lip = [string]$cfg.IPv4Address.IPAddress
      if ($lip -and $lip -notlike "127.*") {
        [void]$localIps.Add($lip)
        if ($lip -match "^(\d+\.\d+\.\d+)\.\d+$") {
          $prefixes[$matches[1]] = $true
        }
      }
      if ($cfg.IPv4DefaultGateway) {
        Add-Candidate -Ip ([string]$cfg.IPv4DefaultGateway.NextHop)
      }
    }
  } catch {
  }

  try {
    $arpLines = arp -a 2>$null
    foreach ($ln in $arpLines) {
      if ($ln -match "^\s*(\d+\.\d+\.\d+\.\d+)\s+[0-9a-fA-F\-]{11,17}\s+\w+") {
        Add-Candidate -Ip $matches[1]
      }
    }
  } catch {
  }

  foreach ($prefix in $prefixes.Keys) {
    foreach ($n in 2..254) {
      $ip = "$prefix.$n"
      if ($localIps -contains $ip) { continue }
      Add-Candidate -Ip $ip
    }
  }

  return @($candidates.ToArray())
}

function Discover-TyxtServerIp {
  param(
    [int]$Port = 5000,
    [string]$HintIp = ""
  )
  $candidates = Get-LanCandidateIps -HintIp $HintIp
  if (-not $candidates -or $candidates.Count -le 0) {
    return @{
      ip = ""
      bootstrap = $null
    }
  }

  Write-Host ("[INFO] Auto discovering TYXT server... candidates=" + $candidates.Count) -ForegroundColor Cyan
  $checked = 0
  foreach ($ip in $candidates) {
    $checked += 1
    if (($checked % 40) -eq 0) {
      Write-Host ("[INFO] Scanned " + $checked + " hosts...") -ForegroundColor DarkGray
    }
    if (-not (Test-TcpPortOpen -Ip $ip -Port $Port -TimeoutMs 130)) {
      continue
    }
    $probe = Try-FetchBootstrap -Ip $ip -Port $Port
    if ($probe.ok) {
      $b = $probe.bootstrap
      $foundIp = [string]$ip
      if ($b -and $b.primary_ipv4) {
        $foundIp = [string]$b.primary_ipv4
      }
      Write-Host ("[INFO] TYXT server discovered at " + $foundIp) -ForegroundColor Green
      return @{
        ip = $foundIp
        bootstrap = $b
      }
    }
  }

  return @{
    ip = ""
    bootstrap = $null
  }
}

$root = Resolve-ProjectRoot
$defaultBootstrap = Join-Path $root "certs\lan\lan_bootstrap.json"
$defaultRootCert = Join-Path $root "certs\lan\rootCA.cer"

if (-not $BootstrapPath) { $BootstrapPath = $defaultBootstrap }
if (-not $RootCertPath) { $RootCertPath = $defaultRootCert }

$bootstrap = Try-LoadJson -Path $BootstrapPath

$serverIp = [string]$ServerIp
$domain = ""
if ($bootstrap) {
  if (-not $serverIp) { $serverIp = [string]$bootstrap.primary_ipv4 }
  $domain = [string]$bootstrap.preferred_domain
  if (-not $ServerPort -or $ServerPort -le 0) {
    $ServerPort = [int]$bootstrap.port
  }
}

if (-not $serverIp) {
  $found = Discover-TyxtServerIp -Port $ServerPort
  if ($found -and $found.ip) {
    $serverIp = [string]$found.ip
    if ((-not $bootstrap) -and $found.bootstrap) {
      $bootstrap = $found.bootstrap
      if (-not $domain) { $domain = [string]$bootstrap.preferred_domain }
    }
  }
}
$serverIp = [string]$serverIp
if ([string]::IsNullOrWhiteSpace($serverIp)) {
  Write-Host "[ERROR] Unable to auto-discover TYXT server in this LAN." -ForegroundColor Red
  Write-Host "[ERROR] Please keep server and client on same subnet, then retry."
  Write-Host "[ERROR] Or run: client_join_lan_ui.bat <server_ip>"
  exit 1
}
$serverIp = $serverIp.Trim()

if (-not $bootstrap) {
  $tmpBootstrap = Join-Path $env:TEMP "tyxt_lan_bootstrap.json"
  foreach ($u in @("https://$serverIp`:$ServerPort/tools/lan/bootstrap", "http://$serverIp`:$ServerPort/tools/lan/bootstrap")) {
    $okBoot = Download-FileInsecure -Url $u -OutFile $tmpBootstrap
    if ($okBoot -and (Test-Path -LiteralPath $tmpBootstrap)) {
      $bootstrap = Try-LoadJson -Path $tmpBootstrap
      if ($bootstrap) {
        if (-not $domain) { $domain = [string]$bootstrap.preferred_domain }
        break
      }
    }
  }
}

if (-not (Test-Path -LiteralPath $RootCertPath)) {
  $tmpRoot = Join-Path $env:TEMP "tyxt_rootCA.cer"
  foreach ($u in @("https://$serverIp`:$ServerPort/tools/lan/rootca", "http://$serverIp`:$ServerPort/tools/lan/rootca")) {
    $downloaded = Download-FileInsecure -Url $u -OutFile $tmpRoot
    if ($downloaded -and (Test-Path -LiteralPath $tmpRoot)) {
      $RootCertPath = $tmpRoot
      Write-Host "[INFO] Downloaded root CA from server." -ForegroundColor Cyan
      break
    }
  }
}

if (-not (Test-Path -LiteralPath $RootCertPath)) {
  Write-Host "[ERROR] root CA file not found." -ForegroundColor Red
  Write-Host "Expected path: $RootCertPath"
  Write-Host "You can copy certs\\lan\\rootCA.cer from the server."
  exit 2
}

$installer = Join-Path $PSScriptRoot "install_lan_root_ca.ps1"
if (-not (Test-Path -LiteralPath $installer)) {
  Write-Host "[ERROR] install_lan_root_ca.ps1 not found." -ForegroundColor Red
  exit 3
}
& $installer -RootCertPath $RootCertPath

$hostsReady = $false
if (-not $SkipHosts -and $domain) {
  $hostsReady = Ensure-HostsEntry -Ip $serverIp -Domain $domain
}

$uiUrl = "https://$serverIp`:$ServerPort/"
if ($domain -and $hostsReady) {
  $uiUrl = "https://$domain`:$ServerPort/"
}

Write-Host "[OK] Client setup completed." -ForegroundColor Green
Write-Host "Open URL: $uiUrl"

if (-not $NoOpen) {
  Start-Process $uiUrl | Out-Null
}
