@echo off
rem Uninstall (ASCII-only). Type YES to confirm when asked.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0scripts\uninstall.py"
echo.
pause >nul
