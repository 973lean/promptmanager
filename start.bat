@echo off
rem Opens Prompt Manager without leaving a console window behind.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw pm.py %*) || (start "" pythonw pm.py %*)
