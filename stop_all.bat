@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT Stop All
cd /d "%~dp0"

set "MAX_PASS=5"
set "WAIT_SEC=1"
set "REMAINING=1"

echo.
echo ==========================================
echo   TYXT Stop All
echo ==========================================
echo.
echo [INFO] Stop strategy: multi-pass sweep (max %MAX_PASS% passes)
echo.

for /L %%N in (1,1,%MAX_PASS%) do (
  echo [PASS %%N/%MAX_PASS%] Stopping tunnels ...
  call :kill_tunnels

  echo [PASS %%N/%MAX_PASS%] Stopping launcher windows ...
  call :kill_launchers

  echo [PASS %%N/%MAX_PASS%] Stopping backend python ...
  call :kill_backend

  echo [PASS %%N/%MAX_PASS%] Releasing listeners 5000/5173 ...
  call :release_ports

  call :check_remaining
  if "!REMAINING!"=="0" goto done_ok
  timeout /t %WAIT_SEC% /nobreak >nul
)

echo [WARN] Sweep finished but some targets may still be alive.
echo [HINT] You can run this script once more if needed.
goto done

:kill_tunnels
for %%I in (cloudflared.exe ngrok.exe) do (
  taskkill /F /IM %%I >nul 2>nul
)
exit /b 0

:kill_launchers
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue; foreach ($p in $procs) { $name = ([string]$p.Name).ToLowerInvariant(); $cmd = [string]$p.CommandLine; if (($name -eq 'cmd.exe' -or $name -eq 'powershell.exe' -or $name -eq 'pwsh.exe') -and $cmd) { $lc = $cmd.ToLowerInvariant(); if ($lc.Contains('start_agent.bat') -or $lc.Contains('start_remote_easy') -or $lc.Contains('start_remote_ngrok') -or $lc.Contains('start_') -or $lc.Contains('ollama_multi_agent.py') -or ($lc.Contains('cloudflared') -and $lc.Contains('tunnel')) -or $lc.Contains('ngrok.exe')) { [Console]::WriteLine($p.ProcessId) } } }"') do (
  taskkill /F /T /PID %%P >nul 2>nul
  echo [OK] killed launcher PID %%P
)
exit /b 0

:kill_backend
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue; foreach ($p in $procs) { $name = ([string]$p.Name).ToLowerInvariant(); $cmd = ([string]$p.CommandLine).ToLowerInvariant(); if (($name -eq 'python.exe' -or $name -eq 'pythonw.exe') -and $cmd.Contains('ollama_multi_agent.py')) { [Console]::WriteLine($p.ProcessId) } }"') do (
  taskkill /F /T /PID %%P >nul 2>nul
  echo [OK] killed backend PID %%P
)
exit /b 0

:release_ports
for /f %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids = @{}; foreach ($pt in 5000,5173) { $conns = Get-NetTCPConnection -State Listen -LocalPort $pt -ErrorAction SilentlyContinue; foreach ($c in @($conns)) { $pid = [int]$c.OwningProcess; if (-not $pids.ContainsKey($pid)) { $pids[$pid] = 1; [Console]::WriteLine($pid) } } }"') do (
  taskkill /F /T /PID %%P >nul 2>nul
  echo [OK] released listener owner PID %%P
)
exit /b 0

:check_remaining
set "REMAINING=0"
for /f %%X in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$count = 0; $tp = Get-Process -Name cloudflared,ngrok -ErrorAction SilentlyContinue; if ($tp) { $count += @($tp).Count }; $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue; foreach ($p in $procs) { $name = ([string]$p.Name).ToLowerInvariant(); $cmd = ([string]$p.CommandLine).ToLowerInvariant(); if (($name -eq 'python.exe' -or $name -eq 'pythonw.exe') -and $cmd.Contains('ollama_multi_agent.py')) { $count += 1 } }; foreach ($pt in 5000,5173) { $conns = Get-NetTCPConnection -State Listen -LocalPort $pt -ErrorAction SilentlyContinue; if ($conns) { $count += @($conns).Count } }; [Console]::WriteLine($count)"') do (
  set "LEFT=%%X"
)
if not defined LEFT set "LEFT=0"
if not "!LEFT!"=="0" set "REMAINING=1"
set "LEFT="
if "!REMAINING!"=="0" (
  echo [OK] all target processes and listeners are stopped.
) else (
  echo [INFO] still remaining targets, continue next pass ...
)
exit /b 0

:done_ok
echo [OK] Stop completed in one run.

:done
echo.
echo [DONE]
echo.
pause
exit /b 0
