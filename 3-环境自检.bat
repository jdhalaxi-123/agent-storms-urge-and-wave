@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\3-环境自检.bat" %*
