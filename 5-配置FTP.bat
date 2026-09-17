@echo off
rem Configure the FTP account by editing .env (ASCII-only)
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0deploy\prep_ftp_env.py"
echo.
echo Opening .env in notepad - fill the four FTP lines, save and close it.
start "" notepad "%~dp0.env"
pause
"%PY%" "%~dp0scripts\check_ftp.py"
echo.
pause >nul
