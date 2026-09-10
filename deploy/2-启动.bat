@echo off
rem ===================================================================
rem  Start the service (ASCII-only; Chinese banner is in win_start.ps1)
rem ===================================================================
setlocal
set "HERE=%~dp0"
set "DP=%HERE%deploy\"
set "ROOT=%HERE%"
if not exist "%HERE%deploy\win_start.ps1" set "DP=%HERE%"
if not exist "%HERE%main.py" set "ROOT=%HERE%.."

if not exist "%DP%win_start.ps1" (
  echo.
  echo [ERROR] win_start.ps1 not found - the package looks incomplete.
  echo         Please re-extract the whole zip file.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%DP%win_start.ps1" -Root "%ROOT%"
echo.
echo Service stopped.  Press any key to close...
pause >nul
endlocal
