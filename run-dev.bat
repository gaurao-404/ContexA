@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ContexA] Creating Python environment...
  py -3 -m venv .venv
  if errorlevel 1 goto error
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
if errorlevel 1 goto error
if not exist ".env" copy ".env.example" ".env" >nul
if not exist "frontend\node_modules" (
  echo [ContexA] Installing frontend dependencies...
  start "ContexA Frontend Installer" /D "%~dp0frontend" cmd /k "npm install && npm run dev"
) else (
  start "ContexA Frontend" /D "%~dp0frontend" cmd /k "npm run dev"
)
echo [ContexA] Starting API at http://localhost:8000
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
exit /b 0
:error
echo Setup failed. Check Python/npm availability and the error above.
pause
exit /b 1
