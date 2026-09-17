@echo off
rem Repair + self-check (ASCII-only). Full log is saved to repair_log.txt
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
"%PY%" "%~dp0deploy\repair_env.py" > "%~dp0repair_log.txt" 2>&1
type "%~dp0repair_log.txt"
echo.
echo ============================================================
echo  Full log saved to: %~dp0repair_log.txt
echo ============================================================
pause >nul
