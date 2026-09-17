@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
echo ============================================================
echo   配置课题数据库 FTP（填一次，之后永久生效）
echo ============================================================
echo.
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0setup_ftp.py"
echo.
echo （按任意键关闭本窗口）
pause >nul
