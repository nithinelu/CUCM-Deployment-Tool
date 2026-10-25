@echo off
rem Launch CUCM Greenfield Deployer (no console window).
rem Uses the real Python directly, because the bare "pythonw" on PATH can be the
rem Microsoft Store stub ("Python was not found").
cd /d "%~dp0"

set "PYW=%LocalAppData%\Python\bin\pythonw.exe"
if exist "%PYW%" goto run
set "PYW=%LocalAppData%\Python\pythoncore-3.14-64\pythonw.exe"
if exist "%PYW%" goto run
start "" pyw "%~dp0deployer_app.py"
exit /b

:run
start "" "%PYW%" "%~dp0deployer_app.py"
