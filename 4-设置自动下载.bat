@echo off
rem Register a scheduled task that refreshes data every 30 minutes (ASCII-only)
setlocal
cd /d "%~dp0"
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0deploy\setup_autodownload.py"
echo.
pause >nul
