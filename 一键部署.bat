@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 风暴潮与海浪智能预报助手 - 一键部署

rem 清掉可能失效的系统代理（Clash/V2Ray 没开会让 pip 卡在 ProxyError）
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="

echo ============================================================
echo   一键部署（从零到能用，全程只需要回答两个问题）
echo     1) DeepSeek API Key
echo     2) 课题组 FTP 账号密码
echo ============================================================
echo.
echo [1/4] 安装运行环境与依赖（首次约 5~15 分钟，请勿关窗口）
echo ------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\setup_windows.ps1" -NoStart
if errorlevel 1 (
  echo.
  echo [中止] 环境安装失败，请看上面红字提示。
  echo        常见原因：网络不通、pip 源被拦、磁盘空间不足。
  pause
  exit /b 1
)

echo.
echo [2/4] 配置课题组 FTP（手动填写 .env，最稳，不会被交互坑到）
echo ------------------------------------------------------------
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem 准备 .env：没有就复制模板，并保证 FTP 四行存在（地址端口已写好，账号密码留空）
"%PY%" "%~dp0deploy\prep_ftp_env.py"

echo.
echo 即将打开记事本编辑 .env —— 请把这四行填好，保存并关闭记事本：
echo     FTP_HOST=120.42.36.229
echo     FTP_PORT=22210
echo     FTP_USER=你的账号
echo     FTP_PASS=你的密码
echo （等号后不加引号、行尾不留空格；密码以 ! 结尾时直接复制粘贴）
echo.
start "" notepad "%~dp0.env"
pause

echo 验证 FTP 连接……
"%PY%" "%~dp0scripts\check_ftp.py"
if errorlevel 1 (
  echo.
  echo [提示] FTP 还没通。可以稍后再双击 5-配置FTP.bat 重填再验证；
  echo        先把程序跑起来也行，只是暂时取不到新数据。
  pause
)

echo.
echo [3/4] 安装体检
echo ------------------------------------------------------------
"%PY%" "%~dp0scripts\check_install.py"

echo.
echo [4/4] 启动
echo ------------------------------------------------------------
echo   部署完成。接下来：
echo     · 双击 2-启动.bat 打开对话页面（浏览器访问 http://localhost:7860）
echo     · 双击 4-设置自动下载.bat 可让数据每天自动更新
echo.
set /p GO=现在直接启动吗？(Y/n)：
if /i "%GO%"=="n" goto :done

start "" "%PY%" "%~dp0main.py"
echo 已启动。浏览器请打开 http://localhost:7860

:done
echo.
echo （按任意键关闭本窗口；关闭不影响已启动的服务）
pause >nul
