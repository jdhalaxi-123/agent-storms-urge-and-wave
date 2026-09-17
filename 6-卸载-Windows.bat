@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\6-卸载-Windows.bat" %*
