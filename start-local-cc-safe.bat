@echo off
setlocal EnableExtensions

set "CC_ROOT=E:\ClaudeCode_CN"
if not "%TYXT_CC_ROOT%"=="" set "CC_ROOT=%TYXT_CC_ROOT%"

set "CC_SCRIPT=%CC_ROOT%\start-local-cc-safe.bat"
if exist "%CC_SCRIPT%" (
  if /I not "%CC_SCRIPT%"=="%~f0" (
    call "%CC_SCRIPT%" %*
    exit /b %errorlevel%
  )
)

if not exist "%CC_ROOT%\cli.js" (
  echo [ERROR] cli.js not found under: %CC_ROOT%
  echo         You can set TYXT_CC_ROOT then rerun.
  exit /b 1
)

cd /d "%CC_ROOT%"

set "CLAUDE_CODE_USE_OPENAI=1"
set "CLAUDE_CODE_USE_OLLAMA="
if "%TYXT_CC_OPENAI_SAFE_TOOLS%"=="" set "TYXT_CC_OPENAI_SAFE_TOOLS=Bash,Edit,Read,Write,Grep,Glob,LS"
if "%TYXT_CC_OPENAI_TOOLS_MODE%"=="" set "TYXT_CC_OPENAI_TOOLS_MODE=auto"
set "PYTHONPATH=%~dp0;%PYTHONPATH%"

set "EFFECTIVE_MODE=%TYXT_CC_OPENAI_TOOLS_MODE%"
if /I "%EFFECTIVE_MODE%"=="auto" (
  for /f "delims=" %%M in ('python -c "import os;from cc_tool_compat import resolve_openai_tool_mode;print(resolve_openai_tool_mode(os.getenv('OPENAI_BASE_URL',''), os.getenv('OPENAI_API_KEY',''), os.getenv('OPENAI_MODEL',''), preferred='auto'))" 2^>nul') do set "EFFECTIVE_MODE=%%M"
)
if "%EFFECTIVE_MODE%"=="" set "EFFECTIVE_MODE=safe"
set "TOOLS_VALUE="
if /I "%EFFECTIVE_MODE%"=="safe" set "TOOLS_VALUE=%TYXT_CC_OPENAI_SAFE_TOOLS%"

echo [INFO] CC root: %CC_ROOT%
echo [INFO] OpenAI tools mode: %EFFECTIVE_MODE%
if not "%TOOLS_VALUE%"=="" echo [INFO] OpenAI safe tools: %TOOLS_VALUE%
echo [INFO] OPENAI_BASE_URL: %OPENAI_BASE_URL%
echo [INFO] OPENAI_MODEL: %OPENAI_MODEL%
echo.

if "%~1"=="" (
  echo [INFO] Starting interactive CC...
  if "%TOOLS_VALUE%"=="" (
    bun cli.js
  ) else (
    bun cli.js --tools "%TOOLS_VALUE%"
  )
  exit /b %errorlevel%
)

echo [INFO] Running one-shot print mode...
if "%TOOLS_VALUE%"=="" (
  bun cli.js --print --output-format text --max-turns 8 -- %*
) else (
  bun cli.js --print --output-format text --max-turns 8 --tools "%TOOLS_VALUE%" -- %*
)
exit /b %errorlevel%
