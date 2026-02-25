@echo off
REM ============================================================
REM  LUTH — Build standalone .exe with PyInstaller
REM ============================================================

title LUTH Build
color 0E

echo.
echo  ====================================================
echo       L U T H  —  Build Windows .exe
echo  ====================================================
echo.

cd /d "%~dp0"

REM Activate venv if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Check PyInstaller
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo  Installing PyInstaller...
    pip install pyinstaller
)

echo  Building LUTH.exe...
echo.
pyinstaller LUTH.spec --noconfirm

if errorlevel 1 (
    echo.
    echo  ERROR: Build failed!
    pause
    exit /b 1
)

REM Create runtime directories
if not exist "dist\LUTH\output" mkdir "dist\LUTH\output"
if not exist "dist\LUTH\input" mkdir "dist\LUTH\input"
if not exist "dist\LUTH\cookies" mkdir "dist\LUTH\cookies"

REM Copy .env.example
copy .env.example "dist\LUTH\.env.example" >nul 2>&1

echo.
echo  ====================================================
echo       BUILD COMPLETE!
echo  ====================================================
echo.
echo  Output: dist\LUTH\LUTH.exe
echo.
echo  To distribute: zip the dist\LUTH\ folder
echo  and send it to your friends.
echo.
pause
