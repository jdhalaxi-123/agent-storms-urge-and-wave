@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\5-配置FTP.bat" %*
