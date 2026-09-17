@echo off
rem Start the web UI (ASCII-only)
setlocal
cd /d "%~dp0"
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
if not exist "%~dp0.venv\Scripts\python.exe" goto :no_env
echo Starting ... browser will open http://localhost:7860
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
goto :done
:no_env
echo [ERROR] Environment not installed. Run the 1st button (deploy) first.
:done
pause
