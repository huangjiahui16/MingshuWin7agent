@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
rem Pick runtime: prefer matching arch, then whatever exists
set "PY="
set "PYW="
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" if exist "runtime\python-portable-amd64\python.exe" set "PY=runtime\python-portable-amd64\python.exe"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if exist "runtime\python-portable-win32\python.exe" set "PY=runtime\python-portable-win32\python.exe"
if not defined PY if exist "runtime\python-portable-amd64\python.exe" set "PY=runtime\python-portable-amd64\python.exe"
if not defined PY if exist "runtime\python-portable-win32\python.exe" set "PY=runtime\python-portable-win32\python.exe"
if not defined PY set "PY=python"
rem pythonw = no console window at all
if exist "runtime\python-portable-amd64\pythonw.exe" set "PYW=runtime\python-portable-amd64\pythonw.exe"
if not defined PYW if exist "runtime\python-portable-win32\pythonw.exe" set "PYW=runtime\python-portable-win32\pythonw.exe"
if not defined PYW if exist "pythonw.exe" set "PYW=pythonw.exe"
if defined PYW goto gui
echo [MingShu Win7] pythonw.exe not found, fallback to console mode.
"%PY%" src\wb_app.py
echo.
echo [MingShu Win7] Exited. Check crash.log in this folder for details.
pause
exit /b 0

:gui
echo [MingShu Win7] Starting without console window...
start "" "%PYW%" src\wb_app.py
exit /b 0
