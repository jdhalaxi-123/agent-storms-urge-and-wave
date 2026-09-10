@echo off
rem ===================================================================
rem  Environment self-check (ASCII-only; Chinese banner in win_check.ps1)
rem ===================================================================
setlocal
set "HERE=%~dp0"
set "DP=%HERE%deploy\"
set "ROOT=%HERE%"
if not exist "%HERE%deploy\win_check.ps1" set "DP=%HERE%"
if not exist "%HERE%main.py" set "ROOT=%HERE%.."

rem strip the trailing backslash of %~dp0 (it would escape the quote)
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%DP%win_check.ps1" -Root "%ROOT%"
echo.
echo Press any key to close this window...
pause >nul
endlocal
