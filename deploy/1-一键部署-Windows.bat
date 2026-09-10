@echo off
rem ===================================================================
rem  One-click deploy  (ASCII-only on purpose: cmd.exe on Chinese
rem  Windows uses GBK, so all Chinese text lives in the .ps1 files.)
rem ===================================================================
setlocal
set "HERE=%~dp0"
set "DP=%HERE%deploy\"
set "ROOT=%HERE%"
if not exist "%HERE%deploy\setup_windows.ps1" set "DP=%HERE%"
if not exist "%HERE%main.py" set "ROOT=%HERE%.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%DP%setup_windows.ps1" -Root "%ROOT%"
set EC=%ERRORLEVEL%

if not "%EC%"=="0" (
  echo.
  echo [WARN] exit code %EC%
  echo        If you cannot fix it yourself, run the 3rd .bat file
  echo        ^(environment self-check^) and send the report to your
  echo        AI assistant / support.
)
echo.
echo Press any key to close this window...
pause >nul
endlocal
