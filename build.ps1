<#
.SYNOPSIS
    LUTH — Build Script (PowerShell)
    Creates a standalone Windows EXE with everything bundled:
      Python + all dependencies + Playwright driver + FFmpeg

.DESCRIPTION
    Output:
      dist\LUTH\LUTH.exe  — Standalone app (just double-click!)
      dist\LUTH_Setup.exe — Windows installer (if Inno Setup found)

.EXAMPLE
    .\build.ps1
#>

$Host.UI.RawUI.WindowTitle = "LUTH Build"

Write-Host ""
Write-Host "  ====================================================" -ForegroundColor Yellow
Write-Host "       L U T H   —   Build Standalone EXE" -ForegroundColor Yellow
Write-Host "  ====================================================" -ForegroundColor Yellow
Write-Host ""

Set-Location $PSScriptRoot

# Activate venv if it exists
if (Test-Path "venv\Scripts\Activate.ps1") {
    & .\venv\Scripts\Activate.ps1
} elseif (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

# Install build tools + all dependencies
Write-Host "[1/4] Installing dependencies..." -ForegroundColor Cyan
pip install pyinstaller 2>&1 | Out-Null
pip install -r requirements.txt 2>&1 | Out-Null
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# Download FFmpeg if not available
Write-Host "[2/4] Checking FFmpeg..." -ForegroundColor Cyan
if (Test-Path "bin\ffmpeg.exe") {
    Write-Host "        FFmpeg found in bin\" -ForegroundColor Green
} else {
    $ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $ffmpegCheck) {
        Write-Host "        FFmpeg not found. Downloading..." -ForegroundColor Yellow
        & python -c "from utils.auto_setup import download_ffmpeg; download_ffmpeg()"
    } else {
        Write-Host "        FFmpeg found in PATH" -ForegroundColor Green
    }
}
Write-Host ""

# Run PyInstaller
Write-Host "[3/4] Building with PyInstaller (this takes a few minutes)..." -ForegroundColor Cyan
& pyinstaller --clean --noconfirm LUTH.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  ERROR: PyInstaller build failed!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Create runtime directories
New-Item -ItemType Directory -Path "dist\LUTH\output" -Force | Out-Null
New-Item -ItemType Directory -Path "dist\LUTH\input" -Force | Out-Null
New-Item -ItemType Directory -Path "dist\LUTH\cookies" -Force | Out-Null
Copy-Item ".env.example" "dist\LUTH\.env.example" -ErrorAction SilentlyContinue
Write-Host "        OK" -ForegroundColor Green
Write-Host ""

# Build installer with Inno Setup (optional)
Write-Host "[4/4] Building Windows installer..." -ForegroundColor Cyan
$iscc = $null
$paths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
)
foreach ($p in $paths) {
    if (Test-Path $p) { $iscc = $p; break }
}

if ($iscc) {
    & $iscc installer.iss
    Write-Host "        OK" -ForegroundColor Green
} else {
    Write-Host "        Inno Setup not found — skipping installer." -ForegroundColor Yellow
    Write-Host "        You can still use dist\LUTH\LUTH.exe directly!"
}
Write-Host ""

Write-Host "  ====================================================" -ForegroundColor Green
Write-Host "       BUILD COMPLETE!" -ForegroundColor Green
Write-Host "  ====================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Standalone app:  dist\LUTH\LUTH.exe"
Write-Host "  Just ZIP the dist\LUTH\ folder and share it!"
Write-Host ""
Read-Host "Press Enter to exit"
