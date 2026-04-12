param(
  [switch]$RemoveOld,
  [switch]$ForceRemove
)

$oldDir = 'E:\ClawLibrary-main'

Write-Host "[Scan] Looking for processes referencing $oldDir ..."
$targets = Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and (
    ($_.CommandLine -and $_.CommandLine -like "*$oldDir*") -or
    ($_.ExecutablePath -and $_.ExecutablePath -like "$oldDir*")
  )
}

if (-not $targets) {
  Write-Host "[Info] No matching process found."
} else {
  Write-Host "[Info] Found $($targets.Count) process(es):"
  $targets | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize

  foreach ($p in $targets) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
      Write-Host "[Killed] PID=$($p.ProcessId) Name=$($p.Name)"
    } catch {
      Write-Host "[Failed] PID=$($p.ProcessId) Name=$($p.Name) Reason=$($_.Exception.Message)"
    }
  }
}

function Try-RemoveOld {
  param([string]$Target)
  if (-not (Test-Path -LiteralPath $Target)) {
    Write-Host "[Info] Old folder does not exist: $Target"
    return $true
  }
  try {
    Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction Stop
    Write-Host "[Done] Removed old folder: $Target"
    return $true
  } catch {
    Write-Host "[Warn] Could not remove old folder: $($_.Exception.Message)"
    return $false
  }
}

if ($RemoveOld -or $ForceRemove) {
  Start-Sleep -Milliseconds 700
  $removed = Try-RemoveOld -Target $oldDir

  if (-not $removed -and $ForceRemove) {
    Write-Host "[Force] Restarting Explorer and retrying..."
    try {
      Get-Process explorer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 700
      $removed = Try-RemoveOld -Target $oldDir
    } finally {
      Start-Process explorer.exe | Out-Null
    }
  }

  if (-not $removed) {
    Write-Host "[Hint] Close Explorer windows in $oldDir and retry with --force-remove."
    exit 2
  }
}

exit 0
