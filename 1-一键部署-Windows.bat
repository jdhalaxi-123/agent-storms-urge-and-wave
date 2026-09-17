@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\1-一键部署-Windows.bat" %*
