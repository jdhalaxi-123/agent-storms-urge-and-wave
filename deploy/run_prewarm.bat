@echo off
rem Wrapper for the scheduled task: run the daily prewarm quietly.
cd /d "%~dp0.."
".venv\Scripts\pythonw.exe" "scripts\daily_prewarm.py" --quiet
