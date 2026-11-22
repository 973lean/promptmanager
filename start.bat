@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py pm.py %*) || (python pm.py %*)
pause
