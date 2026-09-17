@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
echo ============================================================
echo   卸载：风暴潮与海浪智能预报助手
echo   （会先列出要删什么，需要输入 YES 才真正执行）
echo ============================================================
echo.
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0..\scripts\uninstall.py"
echo.
echo （按任意键关闭本窗口）
pause >nul
