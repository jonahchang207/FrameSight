@echo off
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python not found.
    echo.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during install.
    echo.
    pause
    exit /b 1
)

python setup_wizard.py
if %errorlevel% neq 0 pause
