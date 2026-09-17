@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\4-设置自动下载.bat" %*
