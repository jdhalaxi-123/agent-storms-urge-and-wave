@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title 一键修复 + 自检（依赖 / 取数 / 出图）

echo ============================================================
echo   一键修复 + 自检
echo     ① 清掉失效代理  ② 装齐依赖
echo     ③ 实测 FTP 取数 ④ 实测画一张图
echo ============================================================
echo.
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0repair_env.py"
echo.
echo （按任意键关闭本窗口）
pause >nul
