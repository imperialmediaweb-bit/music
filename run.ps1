<#
.SYNOPSIS
    LUTH — PowerShell automation script for the music pipeline.
    Native PowerShell launcher for the LUTH music pipeline.

.DESCRIPTION
    Full automation: generate music, merge, thumbnail, video, upload to
    YouTube, TikTok, TuneCore, and SoundCloud.

.EXAMPLE
    .\run.ps1                  # Launch LUTH GUI
    .\run.ps1 gui              # Launch LUTH GUI
    .\run.ps1 cli              # Run pipeline once (1 clip)
    .\run.ps1 cli 3            # Run pipeline 3 times
    .\run.ps1 schedule         # Start scheduler (3 clips/day at 13:00, 16:00, 19:00)
    .\run.ps1 autostart        # Auto-start scheduler on Windows login
    .\run.ps1 login            # Login to aimusicfactory
    .\run.ps1 tiktok-login     # Login to TikTok
    .\run.ps1 youtube-login    # Login to YouTube
    .\run.ps1 tunecore-login   # Login to TuneCore
    .\run.ps1 soundcloud-login # Login to SoundCloud
    .\run.ps1 suno-login       # Login to Suno
    .\run.ps1 udio-login       # Login to Udio
#>

param(
    [Parameter(Position = 0)]
    [string]$Command = "gui",

    [Parameter(Position = 1)]
    [string]$Arg1 = ""
)

# Ensure we're in the script's directory
Set-Location $PSScriptRoot

# Activate virtual environment
if (Test-Path "venv\Scripts\Activate.ps1") {
    & .\venv\Scripts\Activate.ps1
} elseif (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

function Start-Pipeline {
    param([int]$Count = 1)
    Write-Host "Running pipeline $Count time(s)..." -ForegroundColor Cyan
    & python main.py run -n $Count
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nPipeline finished with errors. Check output\pipeline.log" -ForegroundColor Red
    }
}

switch ($Command.ToLower()) {
    "gui" {
        Write-Host "Starting LUTH GUI..." -ForegroundColor Cyan
        Start-Process pythonw -ArgumentList "app.py" -WindowStyle Normal
    }
    "cli" {
        if ($Arg1 -and $Arg1 -match '^\d+$') {
            Start-Pipeline -Count ([int]$Arg1)
        } else {
            Start-Pipeline -Count 1
        }
    }
    "schedule" {
        Write-Host "Starting scheduler (press Ctrl+C to stop)..." -ForegroundColor Cyan
        & python main.py schedule
    }
    "autostart" {
        Write-Host "Setting up auto-start on Windows login..." -ForegroundColor Cyan
        & python main.py autostart
    }
    "login"            { & python main.py login }
    "suno-login"       { & python main.py suno-login }
    "udio-login"       { & python main.py udio-login }
    "tiktok-login"     { & python main.py tiktok-login }
    "youtube-login"    { & python main.py youtube-login }
    "tunecore-login"   { & python main.py tunecore-login }
    "soundcloud-login" { & python main.py soundcloud-login }
    default {
        # If argument looks like a number, treat it as cli N
        if ($Command -match '^\d+$') {
            Start-Pipeline -Count ([int]$Command)
        } else {
            Write-Host "Unknown command: $Command" -ForegroundColor Red
            Write-Host ""
            Write-Host "Usage:" -ForegroundColor Yellow
            Write-Host "  .\run.ps1              — Launch LUTH GUI"
            Write-Host "  .\run.ps1 cli          — Run pipeline once"
            Write-Host "  .\run.ps1 cli 3        — Run pipeline 3 times"
            Write-Host "  .\run.ps1 schedule     — Start daily scheduler"
            Write-Host "  .\run.ps1 autostart    — Auto-start on Windows login"
            Write-Host "  .\run.ps1 login        — Login to aimusicfactory"
            Write-Host "  .\run.ps1 *-login      — Login to specific platform"
        }
    }
}
