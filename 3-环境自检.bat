@echo off
rem Environment self-check (ASCII-only; report content is written by Python)
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0deploy\check_env.py"
echo.
pause >nul
