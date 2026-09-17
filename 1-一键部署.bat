@echo off
rem One-click deploy. ASCII-only on purpose: cmd.exe code pages vary,
rem so every Chinese message is printed by the Python scripts instead.
setlocal
cd /d "%~dp0"

rem Clear broken proxies (Clash/V2Ray not running would break pip)
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="

echo ============================================================
echo   One-click deploy
echo     1) install Python env + dependencies
echo     2) fill DeepSeek API Key
echo     3) fill FTP account
echo     4) self-check, then start
echo ============================================================
echo.

set "BOOT="
if exist "%~dp0.venv\Scripts\python.exe" set "BOOT=%~dp0.venv\Scripts\python.exe"
if not defined BOOT if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "BOOT=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined BOOT if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "BOOT=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined BOOT if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "BOOT=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined BOOT if exist "C:\Python310\python.exe" set "BOOT=C:\Python310\python.exe"
if not defined BOOT if exist "C:\Python311\python.exe" set "BOOT=C:\Python311\python.exe"
if not defined BOOT for /f "delims=" %%P in ('where python 2^>nul') do if not defined BOOT set "BOOT=%%P"

if defined BOOT goto :have_python
echo [INFO] No Python found. Downloading Python 3.10.11 (user install, no admin needed)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $d=Join-Path $env:TEMP 'py310.exe'; foreach($u in @('https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe','https://mirrors.huaweicloud.com/python/3.10.11/python-3.10.11-amd64.exe')){ try { Invoke-WebRequest -Uri $u -OutFile $d -TimeoutSec 300; break } catch {} }; if (Test-Path $d) { Start-Process -FilePath $d -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1',('TargetDir='+(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310')) -Wait }"
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "BOOT=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

:have_python
if not defined BOOT goto :no_python
echo [INFO] Using Python: %BOOT%
echo.
"%BOOT%" "%~dp0deploy\setup_env.py"
if errorlevel 1 goto :setup_failed

"%BOOT%" "%~dp0deploy\prep_ftp_env.py"
echo.
echo Opening .env in notepad - fill the four FTP lines, save and close it.
start "" notepad "%~dp0.env"
pause
"%BOOT%" "%~dp0scripts\check_ftp.py"
echo.
"%BOOT%" "%~dp0scripts\check_install.py"
echo.
set /p GO=Start now? (Y/n):
if /i "%GO%"=="n" goto :done
start "" "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
echo Started. Open http://localhost:7860 in your browser.
goto :done

:no_python
echo [ERROR] Could not prepare Python automatically.
echo         Install Python 3.10 manually, then run this file again.
echo         https://www.python.org/downloads/release/python-31011/
goto :done

:setup_failed
echo.
echo [WARN] Setup reported problems, see the lines above.
echo        You can also run the 7th button (repair and self-check) to retry.

:done
echo.
echo Press any key to close this window.
pause >nul
