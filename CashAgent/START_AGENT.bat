@echo off
echo =========================================
echo   Cash's AI Agent -- Grubbs Infiniti
echo =========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Install from python.org and check "Add to PATH"
    pause
    exit /b 1
)

echo Installing dependencies...
pip install anthropic browser-use langchain-anthropic playwright pydantic
echo.
echo Installing Chromium...
python -m playwright install chromium
echo.
echo Starting agent...
echo.
python dashboard.py

if errorlevel 1 (
    echo.
    echo Something crashed. See error above.
    pause
)
