@echo off
REM ============================================================
REM  LUTH — Build Script
REM  Creates a standalone Windows EXE with everything bundled:
REM    Python + all dependencies + Playwright driver + FFmpeg
REM
REM  Output:
REM    dist\LUTH\LUTH.exe  — Standalone app (just double-click!)
REM    dist\LUTH_Setup.exe — Windows installer (if Inno Setup found)
REM ============================================================

title LUTH Build
color 0E

echo.
echo  ====================================================
echo       L U T H   —   Build Standalone EXE
echo  ====================================================
echo.

cd /d "%~dp0"

REM Activate venv if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Install build tools + all dependencies
echo [1/4] Installing dependencies...
pip install pyinstaller >nul 2>&1
pip install -r requirements.txt >nul 2>&1
echo         OK
echo.

REM Download FFmpeg if not available
echo [2/4] Checking FFmpeg...
if exist "bin\ffmpeg.exe" (
    echo         FFmpeg found in bin\
) else (
    ffmpeg -version >nul 2>&1
    if errorlevel 1 (
        echo         FFmpeg not found. Downloading...
        python -c "from utils.auto_setup import download_ffmpeg; download_ffmpeg()"
    ) else (
        echo         FFmpeg found in PATH
    )
)
echo.

REM Run PyInstaller
echo [3/4] Building with PyInstaller (this takes a few minutes)...
pyinstaller --clean --noconfirm LUTH.spec
if errorlevel 1 (
    echo.
    echo  ERROR: PyInstaller build failed!
    pause
    exit /b 1
)

REM Create runtime directories
if not exist "dist\LUTH\output" mkdir "dist\LUTH\output"
if not exist "dist\LUTH\input" mkdir "dist\LUTH\input"
if not exist "dist\LUTH\cookies" mkdir "dist\LUTH\cookies"
copy .env.example "dist\LUTH\.env.example" >nul 2>&1
echo         OK
echo.

REM Build installer with Inno Setup (optional)
echo [4/4] Building Windows installer...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if defined ISCC (
    "%ISCC%" installer.iss
    echo         OK
) else (
    echo         Inno Setup not found — skipping installer.
    echo         You can still use dist\LUTH\LUTH.exe directly!
)
echo.

echo  ====================================================
echo       BUILD COMPLETE!
echo  ====================================================
echo.
echo  Standalone app:  dist\LUTH\LUTH.exe
echo  Just ZIP the dist\LUTH\ folder and share it!
echo.
pause
