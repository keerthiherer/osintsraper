@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 (
        echo Could not create a virtual environment. Install Python 3.10+ and retry.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
)

".venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed.
        pause
        exit /b 1
    )
)

echo Starting MindSmiths Sales Intelligence Platform...
".venv\Scripts\python.exe" -m streamlit run app.py --server.gatherUsageStats false
pause
