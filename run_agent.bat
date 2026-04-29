@echo off
setlocal

cd /d "%~dp0"

echo Starting NetLens Agent...
echo Open frontend/index.html in your browser
echo Press Ctrl+C to stop
echo.

if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  echo No venv found. Trying system Python environment.
)

where uvicorn >nul 2>nul
if errorlevel 1 (
  if exist "backend\requirements.txt" (
    echo Installing requirements...
    python -m pip install -r backend\requirements.txt
  ) else if exist "requirements.txt" (
    echo Installing requirements...
    python -m pip install -r requirements.txt
  )
)

where uvicorn >nul 2>nul
if errorlevel 1 (
  echo.
  echo uvicorn is not installed.
  echo Install it with: python -m pip install fastapi uvicorn
  echo Then run this file again.
  pause
  exit /b 1
)

cd /d "%~dp0backend"
uvicorn main:app --host 127.0.0.1 --port 8000

endlocal
