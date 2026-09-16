@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"
set "PY=%ROOT%\.venv\Scripts\pythonw.exe"
set "TASK=StormSurge-DailyPrewarm"

echo ============================================================
echo   Set up automatic daily data download
echo ============================================================
echo.
echo   Program dir : %ROOT%
echo   Task name   : %TASK%
echo   Schedule    : every 30 minutes, all day
echo   Downloads   : daily AI forecast (surge/wave/points, few MB)
echo                 + daily wind field (259 MB, keeps latest 30 days)
echo.

if not exist "%PY%" (
  echo [ERROR] python not found: %PY%
  echo         Please run 1-Setup-Windows.bat first.
  pause
  exit /b 1
)

echo [1/2] Registering scheduled task ...
schtasks /Create /F /TN "%TASK%" /SC MINUTE /MO 30 /TR "\"%ROOT%\deploy\run_prewarm.bat\"" >nul
if errorlevel 1 (
  echo [ERROR] failed to create task. Try running this file as Administrator.
  pause
  exit /b 1
)

echo [2/2] Running one check now ...
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\daily_prewarm.py"

echo.
echo Done.  Task "%TASK%" is active (checks every 30 minutes).
echo   log file : %ROOT%\stormdata\logs\prewarm.log
echo.
echo   To see it   : schtasks /Query /TN "%TASK%"
echo   To run now  : schtasks /Run   /TN "%TASK%"
echo   To remove it: schtasks /Delete /F /TN "%TASK%"
echo   No wind data (saves 259 MB/day): edit deploy\run_prewarm.bat and add --no-wind
echo.
pause
