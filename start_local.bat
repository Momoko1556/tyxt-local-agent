@echo off
setlocal EnableExtensions

title TYXT Local Start
cd /d "%~dp0"

echo.
echo ==========================================
echo   TYXT Local Start
echo ==========================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [WARN] .venv not found. Please run setup first:
  echo [WARN]   setup_start_cn.bat   ^(CN users^)
  echo [WARN]   or setup_project.bat
  echo.
)

call "%~dp0start_agent.bat"

endlocal
