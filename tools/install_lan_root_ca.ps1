[CmdletBinding()]
param(
  [string]$RootCertPath = "",
  [switch]$LocalMachine
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-DefaultCertPath {
  $projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
  $c1 = Join-Path $projectRoot "certs\lan\rootCA.cer"
  $c2 = Join-Path $projectRoot "certs\lan\rootCA.pem"
  if (Test-Path -LiteralPath $c1) { return $c1 }
  if (Test-Path -LiteralPath $c2) { return $c2 }
  return ""
}

$certPath = $RootCertPath
if (-not $certPath) {
  $certPath = Resolve-DefaultCertPath
}
if (-not $certPath) {
  Write-Host "[ERROR] root CA file not found. Please set -RootCertPath." -ForegroundColor Red
  exit 1
}
$certPath = (Resolve-Path -LiteralPath $certPath).Path

$importPath = $certPath
if ([System.IO.Path]::GetExtension($importPath).ToLowerInvariant() -ne ".cer") {
  $tmpCer = Join-Path $env:TEMP "tyxt_rootCA.cer"
  Copy-Item -LiteralPath $importPath -Destination $tmpCer -Force
  $importPath = $tmpCer
}

$store = if ($LocalMachine) { "Cert:\LocalMachine\Root" } else { "Cert:\CurrentUser\Root" }

try {
  $res = Import-Certificate -FilePath $importPath -CertStoreLocation $store -ErrorAction Stop
  $thumb = ""
  try { $thumb = ($res | Select-Object -First 1).Thumbprint } catch {}
  Write-Host "[OK] Root CA imported to $store" -ForegroundColor Green
  if ($thumb) {
    Write-Host "Thumbprint: $thumb"
  }
  exit 0
} catch {
  Write-Host "[WARN] Import-Certificate failed, fallback to certutil..." -ForegroundColor Yellow
}

try {
  if ($LocalMachine) {
    certutil -addstore root $importPath | Out-Host
  } else {
    certutil -user -addstore root $importPath | Out-Host
  }
  Write-Host "[OK] Root CA imported via certutil." -ForegroundColor Green
  exit 0
} catch {
  Write-Host "[ERROR] Failed to import root CA: $($_.Exception.Message)" -ForegroundColor Red
  exit 2
}
