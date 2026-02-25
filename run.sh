#!/usr/bin/env bash
# Music Pipeline — Linux/macOS starter script
# Runs the full pipeline once (generate music + merge + thumbnail + video + upload)
#
# Usage:
#   ./run.sh              — Run pipeline once (1 clip)
#   ./run.sh 3            — Run pipeline 3 times (3 clips)
#   ./run.sh schedule     — Start APScheduler (keeps running)
#   ./run.sh setup        — Install crontab entries (runs in background)

set -e
cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

case "${1:-}" in
    schedule)
        echo "Starting scheduler (press Ctrl+C to stop)..."
        python main.py schedule
        ;;
    setup)
        echo "Setting up crontab entries..."
        python main.py setup-schedule
        ;;
    login)
        python main.py login
        ;;
    tiktok-login)
        python main.py tiktok-login
        ;;
    "")
        echo "Running pipeline once (1 clip)..."
        python main.py run -n 1
        ;;
    *)
        echo "Running pipeline $1 time(s)..."
        python main.py run -n "$1"
        ;;
esac
