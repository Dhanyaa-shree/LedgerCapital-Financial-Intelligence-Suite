@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 (echo Python 3.11 is required & exit /b 1)
)
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements-verified.txt
if errorlevel 1 (echo Backend dependency installation failed & exit /b 1)
start "LedgerCapital API" "%ComSpec%" /k ""%~dp0.venv\Scripts\python.exe" "%~dp0verified_server.py""
cd frontend
if not exist node_modules call npm install
if errorlevel 1 (echo Frontend dependency installation failed & exit /b 1)
npm run dev
