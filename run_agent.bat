@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo Creating a virtual environment...
  python -m venv venv || (
    echo Python 3.11 or newer is required: https://www.python.org/downloads/
    pause
    exit /b 1
  )
)

call "venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r backend\requirements.txt || (
  echo Could not install requirements.
  pause
  exit /b 1
)

echo.
echo NetLens agent running at http://127.0.0.1:8000
echo Press Ctrl+C to stop.
echo.
start "" "http://127.0.0.1:8000"
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
endlocal
