<#
.SYNOPSIS
    LUTH — One-Click Windows Installer (PowerShell)
    Installs Python dependencies, Playwright, FFmpeg and
    sets up everything needed to run the music pipeline.

.EXAMPLE
    .\install.ps1
#>

$Host.UI.RawUI.WindowTitle = "LUTH Installer"

Write-Host ""
Write-Host "  ====================================================" -ForegroundColor Green
Write-Host "       L U T H   —   Installer" -ForegroundColor Green
Write-Host "       Music Pipeline Setup for Windows" -ForegroundColor Green
Write-Host "  ====================================================" -ForegroundColor Green
Write-Host ""

Set-Location $PSScriptRoot

# ----------------------------------------------------------
# 1. Check Python
# ----------------------------------------------------------
Write-Host "[1/6] Checking Python..." -ForegroundColor Cyan
$pythonCheck = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCheck) {
    Write-Host ""
    Write-Host "  ERROR: Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Please install Python 3.10+ from:"
    Write-Host "    https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "  IMPORTANT: Check 'Add Python to PATH' during install!"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
& python --version
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------------
# 2. Create virtual environment
# ----------------------------------------------------------
Write-Host "[2/6] Setting up virtual environment..." -ForegroundColor Cyan
if (-not (Test-Path "venv")) {
    & python -m venv venv
    Write-Host "        Created new virtual environment." -ForegroundColor Green
} else {
    Write-Host "        Virtual environment already exists." -ForegroundColor Green
}
& .\venv\Scripts\Activate.ps1
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------------
# 3. Install Python dependencies
# ----------------------------------------------------------
Write-Host "[3/6] Installing Python dependencies..." -ForegroundColor Cyan
& pip install --upgrade pip 2>&1 | Out-Null
& pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  ERROR: Failed to install Python dependencies." -ForegroundColor Red
    Write-Host "  Check your internet connection and try again."
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------------
# 4. Install Playwright browsers
# ----------------------------------------------------------
Write-Host "[4/6] Installing Playwright browsers (Chromium)..." -ForegroundColor Cyan
& python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  WARNING: Playwright browser install failed." -ForegroundColor Yellow
    Write-Host "  You can try manually: python -m playwright install chromium"
    Write-Host ""
}
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------------
# 5. Check/Install FFmpeg
# ----------------------------------------------------------
Write-Host "[5/6] Checking FFmpeg..." -ForegroundColor Cyan
$ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCheck) {
    Write-Host "  FFmpeg not found. Attempting to install via winget..." -ForegroundColor Yellow
    & winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  WARNING: Could not auto-install FFmpeg." -ForegroundColor Yellow
        Write-Host "  Please install FFmpeg manually:"
        Write-Host "    1. Download from https://ffmpeg.org/download.html"
        Write-Host "    2. Extract and add the bin\ folder to your system PATH"
        Write-Host "    3. Restart this installer"
        Write-Host ""
    } else {
        Write-Host "        FFmpeg installed via winget." -ForegroundColor Green
    }
} else {
    Write-Host "        FFmpeg found." -ForegroundColor Green
}
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------------
# 6. Create .env file if missing
# ----------------------------------------------------------
Write-Host "[6/6] Checking configuration..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env" -ErrorAction SilentlyContinue
    Write-Host "        Created .env from template." -ForegroundColor Green
    Write-Host "        IMPORTANT: Open LUTH and enter your OpenAI API key in Settings!" -ForegroundColor Yellow
} else {
    Write-Host "        .env already exists." -ForegroundColor Green
}
Write-Host ""

# ----------------------------------------------------------
# Create desktop shortcut (PowerShell-based, no CMD)
# ----------------------------------------------------------
Write-Host "Creating desktop shortcut..." -ForegroundColor Cyan
$scriptDir = $PSScriptRoot
$desktopPath = [Environment]::GetFolderPath("Desktop")

# Create a .lnk shortcut that runs PowerShell hidden
$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut("$desktopPath\LUTH.lnk")
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -Command `"Set-Location '$scriptDir'; if (Test-Path 'venv\Scripts\Activate.ps1') { & '.\venv\Scripts\Activate.ps1' }; Start-Process pythonw -ArgumentList 'app.py' -WorkingDirectory '$scriptDir'`""
$shortcut.WorkingDirectory = $scriptDir
$shortcut.IconLocation = "$scriptDir\assets\icon.ico,0"
$shortcut.Save()
Write-Host "        Desktop shortcut created: LUTH.lnk" -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------------
# Done!
# ----------------------------------------------------------
Write-Host ""
Write-Host "  ====================================================" -ForegroundColor Green
Write-Host "       INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "  ====================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Double-click LUTH on your Desktop to start"
Write-Host "    2. Go to Settings and enter your OpenAI API key"
Write-Host "    3. Go to Logins and log into each service"
Write-Host "    4. Click 'RUN PIPELINE' to generate your first track!"
Write-Host ""
Write-Host "  Or run from command line:"
Write-Host "    .\run.ps1              (GUI mode)"
Write-Host "    .\run.ps1 cli          (command-line mode)"
Write-Host ""
Read-Host "Press Enter to exit"
