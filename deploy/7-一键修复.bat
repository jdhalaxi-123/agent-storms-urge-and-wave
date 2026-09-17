@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title 一键修复 + 自检（依赖 / 取数 / 出图）

set "LOG=%~dp0..\修复日志.txt"
echo ============================================================
echo   一键修复 + 自检
echo     ⓪ 代码版本  ① 清代理  ② 装依赖
echo     ③ 实测取数  ④ 实测出图
echo ============================================================
echo.
echo 正在检查，请稍候（结果同时写入 修复日志.txt）……
echo.

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%~dp0repair_env.py" (
  echo [错误] 找不到 deploy\repair_env.py
  echo        说明这份代码是**旧版**，请到 GitHub 重新下载 ZIP。
  echo.
  echo （按任意键关闭）
  pause >nul
  exit /b 1
)

"%PY%" "%~dp0repair_env.py" 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG%'"
set EC=%ERRORLEVEL%

echo.
echo ============================================================
echo   完成。完整结果已保存到：%LOG%
if not "%EC%"=="0" echo   （有未通过的项，请看上面的 ❌ 行）
echo ============================================================
echo.
echo （按任意键关闭本窗口）
pause >nul
