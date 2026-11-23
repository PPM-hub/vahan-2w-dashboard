@echo off
REM Starts the Vahan dashboard on this computer and opens it in your browser.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) & pause & exit /b)
if not exist ".venv" (
  echo Setting up for first use, please wait...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
streamlit run app.py
