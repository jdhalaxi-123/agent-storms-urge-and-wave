@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
title 配置课题组 FTP（手动填写 .env）

echo ============================================================
echo   配置课题组 FTP（改成手动填写，最稳）
echo ============================================================
echo.
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0prep_ftp_env.py"
if errorlevel 1 (
  echo [提示] 准备 .env 失败，请确认项目目录完整。
  pause
  exit /b 1
)

echo.
echo 现在用记事本打开 .env，把这四行填好、保存、关闭记事本……
start "" notepad "%~dp0..\.env"
echo.
pause

echo 正在验证 FTP 连接……
echo ------------------------------------------------------------
"%PY%" "%~dp0..\scripts\check_ftp.py"
echo ------------------------------------------------------------
echo.
echo 若上面 ③ 登录 显示 ✅ 就配好了；若 ❌ 530，多半是账号或密码写错：
echo   · 密码以 ! 结尾时直接复制粘贴，别手打
echo   · 等号后不要加引号、不要留空格
echo   · 端口是 22210
echo.
echo 改完 .env 保存后，重跑本文件即可再验证一次。
echo.
echo （按任意键关闭本窗口）
pause >nul
