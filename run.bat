@echo off
REM Music Pipeline — Windows starter script
REM Runs the full pipeline once (generate music + merge + thumbnail + video + upload)
REM
REM Usage:
REM   run.bat              — Run pipeline once (1 clip)
REM   run.bat 3            — Run pipeline 3 times (3 clips)
REM   run.bat schedule     — Start APScheduler (keeps running)
REM   run.bat setup        — Install OS scheduled tasks (no PowerShell needed)

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

if "%1"=="schedule" (
    echo Starting scheduler (press Ctrl+C to stop)...
    python main.py schedule
) else if "%1"=="setup" (
    echo Setting up Windows Task Scheduler tasks...
    python main.py setup-schedule
) else if "%1"=="login" (
    python main.py login
) else if "%1"=="tiktok-login" (
    python main.py tiktok-login
) else if "%1"=="" (
    echo Running pipeline once (1 clip)...
    python main.py run -n 1
) else (
    echo Running pipeline %1 time(s)...
    python main.py run -n %1
)

if errorlevel 1 (
    echo.
    echo Pipeline finished with errors. Check output\pipeline.log
    pause
)
