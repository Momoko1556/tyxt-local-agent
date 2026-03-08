@echo off
setlocal EnableExtensions

title TYXT CN Setup and Start
cd /d "%~dp0"

echo.
echo ==========================================
echo   TYXT CN Setup and Start
echo ==========================================
echo.

rem Speed-first defaults for CN users (can be overridden outside)
if "%PIP_DEFAULT_TIMEOUT%"=="" set "PIP_DEFAULT_TIMEOUT=180"
if "%PIP_RETRIES%"=="" set "PIP_RETRIES=5"
if "%TYXT_SKIP_OLLAMA_SETUP%"=="" set "TYXT_SKIP_OLLAMA_SETUP=1"

echo [INFO] TYXT_SKIP_OLLAMA_SETUP=%TYXT_SKIP_OLLAMA_SETUP%
echo [INFO] Use TYXT_SKIP_OLLAMA_SETUP=0 if you want auto Ollama/model bootstrap.
echo.

call :set_mirror_tuna
echo [TRY 1/3] pip mirror: %PIP_INDEX_URL%
call "%~dp0setup_project.bat"
if "%errorlevel%"=="0" goto setup_ok

echo.
echo [WARN] Setup failed on TUNA mirror. Retrying with Aliyun...
call :set_mirror_aliyun
echo [TRY 2/3] pip mirror: %PIP_INDEX_URL%
call "%~dp0setup_project.bat"
if "%errorlevel%"=="0" goto setup_ok

echo.
echo [WARN] Setup failed on Aliyun mirror. Retrying with USTC...
call :set_mirror_ustc
echo [TRY 3/3] pip mirror: %PIP_INDEX_URL%
call "%~dp0setup_project.bat"
if "%errorlevel%"=="0" goto setup_ok

echo.
echo [ERROR] All CN mirror setup attempts failed.
echo [TIP] Check Python installation, network, and firewall/proxy policy.
pause
exit /b 1

:setup_ok
echo.
echo [OK] Setup completed.
echo [INFO] Current pip mirror: %PIP_INDEX_URL%
echo.
choice /C YN /N /M "Start TYXT now? [Y/N]: "
if errorlevel 2 goto done
call "%~dp0start_agent.bat"

:done
echo.
echo [DONE]
exit /b 0

:set_mirror_tuna
set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn"
exit /b 0

:set_mirror_aliyun
set "PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple"
set "PIP_TRUSTED_HOST=mirrors.aliyun.com"
exit /b 0

:set_mirror_ustc
set "PIP_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple"
set "PIP_TRUSTED_HOST=pypi.mirrors.ustc.edu.cn"
exit /b 0
