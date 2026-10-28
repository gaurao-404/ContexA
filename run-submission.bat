@echo off
setlocal
cd /d "%~dp0"
rem Submission profile deliberately disables all external and local AI providers.
rem Copy checks, seeded scenarios, review actions, audit history and publication gates still work.
set "APP_ENV=demo"
set "OLLAMA_ENABLED=false"
set "AI_VERIFICATION_ENABLED=false"
set "ANTHROPIC_API_KEY="
set "VITE_SUBMISSION_MODE=true"

echo.
echo  CONtexA STUDIO  ^|  SUBMISSION MODE
 echo ----------------------------------------------
 echo  Local rules only. Ollama and cloud API keys are not required.
 echo  On first run, Python and npm dependencies may need installation.
 echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ContexA] Creating Python environment...
  py -3 -m venv .venv
  if errorlevel 1 goto error
)
call ".venv\Scripts\activate.bat"
if not exist ".venv\.contexa-backend-ready" (
  echo [ContexA] Installing backend dependencies once...
  python -m pip install --upgrade pip
  if errorlevel 1 goto error
  python -m pip install -r backend\requirements.txt
  if errorlevel 1 goto error
  echo ready>".venv\.contexa-backend-ready"
)
if not exist ".env" copy ".env.example" ".env" >nul
if not exist "frontend\node_modules" (
  echo [ContexA] Installing frontend dependencies once, then starting Vite...
  start "ContexA Frontend - Submission Mode" /D "%~dp0frontend" cmd /k "set VITE_SUBMISSION_MODE=true&& npm install && npm run dev"
) else (
  start "ContexA Frontend - Submission Mode" /D "%~dp0frontend" cmd /k "set VITE_SUBMISSION_MODE=true&& npm run dev"
)
echo [ContexA] Starting API at http://localhost:8000
 echo [ContexA] Frontend at http://localhost:5173
 echo [ContexA] Sign in as admin@contexa.local / ContexA!2026
 echo [ContexA] Use 'Prepare demo workspace' for reproducible sample findings.
 echo.
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
exit /b 0
:error
echo.
echo Setup failed. Check that Python 3, Node.js, and npm are installed.
echo Ollama is not required for Submission Mode.
pause
exit /b 1
