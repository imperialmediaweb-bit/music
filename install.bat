@echo off
REM ============================================================
REM  LUTH — One-Click Windows Installer
REM  Installs Python dependencies, Playwright, FFmpeg and
REM  sets up everything needed to run the music pipeline.
REM ============================================================

title LUTH Installer
color 0A

echo.
echo  ====================================================
echo       L U T H   —   Installer
echo       Music Pipeline Setup for Windows
echo  ====================================================
echo.

cd /d "%~dp0"

REM ----------------------------------------------------------
REM 1. Check Python
REM ----------------------------------------------------------
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Please install Python 3.10+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add Python to PATH" during install!
    echo.
    pause
    exit /b 1
)
python --version
echo         OK
echo.

REM ----------------------------------------------------------
REM 2. Create virtual environment
REM ----------------------------------------------------------
echo [2/6] Setting up virtual environment...
if not exist "venv" (
    python -m venv venv
    echo         Created new virtual environment.
) else (
    echo         Virtual environment already exists.
)
call venv\Scripts\activate.bat
echo         OK
echo.

REM ----------------------------------------------------------
REM 3. Install Python dependencies
REM ----------------------------------------------------------
echo [3/6] Installing Python dependencies...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  ERROR: Failed to install Python dependencies.
    echo  Check your internet connection and try again.
    pause
    exit /b 1
)
echo         OK
echo.

REM ----------------------------------------------------------
REM 4. Install Playwright browsers
REM ----------------------------------------------------------
echo [4/6] Installing Playwright browsers (Chromium)...
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo  WARNING: Playwright browser install failed.
    echo  You can try manually: python -m playwright install chromium
    echo.
)
echo         OK
echo.

REM ----------------------------------------------------------
REM 5. Check/Install FFmpeg
REM ----------------------------------------------------------
echo [5/6] Checking FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo  FFmpeg not found. Attempting to install via winget...
    winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  WARNING: Could not auto-install FFmpeg.
        echo  Please install FFmpeg manually:
        echo    1. Download from https://ffmpeg.org/download.html
        echo    2. Extract and add the bin\ folder to your system PATH
        echo    3. Restart this installer
        echo.
    ) else (
        echo         FFmpeg installed via winget.
    )
) else (
    echo         FFmpeg found.
)
echo         OK
echo.

REM ----------------------------------------------------------
REM 6. Create .env file if missing
REM ----------------------------------------------------------
echo [6/6] Checking configuration...
if not exist ".env" (
    copy .env.example .env >nul 2>&1
    echo         Created .env from template.
    echo         IMPORTANT: Open LUTH and enter your OpenAI API key in Settings!
) else (
    echo         .env already exists.
)
echo.

REM ----------------------------------------------------------
REM Create desktop shortcut
REM ----------------------------------------------------------
echo Creating desktop shortcut...
set "SCRIPT_DIR=%~dp0"
set "SHORTCUT=%USERPROFILE%\Desktop\LUTH.bat"

(
    echo @echo off
    echo cd /d "%SCRIPT_DIR%"
    echo call venv\Scripts\activate.bat
    echo start "" pythonw app.py
) > "%SHORTCUT%"
echo         Desktop shortcut created: LUTH.bat
echo.

REM Create a VBS launcher for no-console start
set "VBS_SHORTCUT=%USERPROFILE%\Desktop\LUTH.vbs"
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.CurrentDirectory = "%SCRIPT_DIR%"
    echo WshShell.Run "cmd /c call venv\Scripts\activate.bat && pythonw app.py", 0, False
) > "%VBS_SHORTCUT%"
echo         Silent launcher created: LUTH.vbs
echo.

REM ----------------------------------------------------------
REM Done!
REM ----------------------------------------------------------
echo.
echo  ====================================================
echo       INSTALLATION COMPLETE!
echo  ====================================================
echo.
echo  Next steps:
echo    1. Double-click LUTH on your Desktop to start
echo    2. Go to Settings and enter your OpenAI API key
echo    3. Go to Logins and log into each service
echo    4. Click "RUN PIPELINE" to generate your first track!
echo.
echo  Or run from command line:
echo    python app.py          (GUI mode)
echo    python main.py run     (command-line mode)
echo.
pause
