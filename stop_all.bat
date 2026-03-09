@echo off
setlocal EnableExtensions EnableDelayedExpansion

title TYXT Stop All
cd /d "%~dp0"

echo.
echo ==========================================
echo   TYXT Stop All
echo ==========================================
echo.

echo [1/4] Stopping tunnel executables ...
for %%I in (cloudflared.exe ngrok.exe) do (
  taskkill /F /IM %%I >nul 2>nul
  if "!errorlevel!"=="0" (
    echo [OK] %%I stopped.
  ) else (
    echo [INFO] %%I not running.
  )
)

echo [2/4] Stopping related CMD/PowerShell launcher windows ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ps=Get-CimInstance Win32_Process | Where-Object { ($_.Name -match 'cmd.exe|powershell.exe') -and ((([string]$_.CommandLine) -like '*start_agent.bat*') -or ((([string]$_.CommandLine) -like '*ollama_multi_agent.py*')) -or ((([string]$_.CommandLine) -like '*start_remote_ngrok*')) -or ((([string]$_.CommandLine) -like '*start_remote_easy*')) -or ((([string]$_.CommandLine) -like '*cloudflared*tunnel*')) -or ((([string]$_.CommandLine) -like '*ngrok.exe*http*127.0.0.1:5000*'))) }; if(-not $ps){Write-Output '[INFO] no related launcher window found.'}; foreach($p in $ps){ try{ Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Output ('[OK] killed launcher PID ' + $p.ProcessId) } catch{} }"

echo [3/4] Stopping backend python process (ollama_multi_agent.py) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ps=Get-CimInstance Win32_Process | Where-Object { ($_.Name -match 'python.exe|pythonw.exe') -and ((([string]$_.CommandLine) -like '*ollama_multi_agent.py*')) }; if(-not $ps){Write-Output '[INFO] no backend python process found.'}; foreach($p in $ps){ try{ Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Output ('[OK] killed backend python PID ' + $p.ProcessId) } catch{} }"

echo [4/4] Releasing port 5000 listener (fallback) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pids=Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if(-not $pids){Write-Output '[INFO] no listener on port 5000.'}; foreach($pid in $pids){ try{ Stop-Process -Id $pid -Force -ErrorAction Stop; Write-Output ('[OK] killed port 5000 owner PID ' + $pid) } catch{} }"

echo.
echo [DONE]
echo.
pause
exit /b 0
