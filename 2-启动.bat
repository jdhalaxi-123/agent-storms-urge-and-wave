@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\2-启动.bat" %*
