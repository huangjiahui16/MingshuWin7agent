@echo off
chcp 65001 >nul
cd /d %~dp0
set "PY="
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" if exist "runtime\python-portable-amd64\python.exe" set "PY=runtime\python-portable-amd64\python.exe"
if "%PROCESSOR_ARCHITECTURE%"=="x86" if exist "runtime\python-portable-win32\python.exe" set "PY=runtime\python-portable-win32\python.exe"
if not defined PY if exist "runtime\python-portable-amd64\python.exe" set "PY=runtime\python-portable-amd64\python.exe"
if not defined PY if exist "runtime\python-portable-win32\python.exe" set "PY=runtime\python-portable-win32\python.exe"
if not defined PY set "PY=python"
echo [MingShu Win7] Python: %PY%
"%PY%" src\win7_assistant.py --cli

echo.
echo [MingShu Win7] Process exited. If there are error messages above, screenshot them.
pause
