@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0deploy\7-一键修复.bat" %*
