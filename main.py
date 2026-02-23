#!/usr/bin/env python3
"""Afro House Music Pipeline — Full automation: generate, merge, thumbnail, video, upload."""

import argparse
import signal
import sys
from pathlib import Path

from config import SCHEDULE_CRON, INPUT_DIR, AIMUSICFACTORY_STATE_FILE
from utils.logger import log

# Default: 4 clips per day
DEFAULT_CLIPS_PER_DAY = 4
# How many MP3s to generate per clip (3-4 generations × 2 = 6-8 MP3s)
MP3S_PER_CLIP = 8


def _run_full_pipeline():
    """Full pipeline: generate music on aimusicfactory → merge → thumbnail → video → upload."""
    from modules.music_generator import generate_music_batch
    from modules.audio_merger import merge_mp3s
    from modules.concept_generator import generate_concept
    from pipeline import process_single_track

    # Step 1: Generate concept first (for the music prompt)
    log.info("=" * 60)
    log.info("STEP 1: Generating Afro House concept...")
    concept = generate_concept()
    log.info(f"Track name: {concept.track_name}")

    # Step 2: Generate music on aimusicfactory.ai (4 generations × 2 MP3s = 8)
    log.info("=" * 60)
    log.info("STEP 2: Generating music on aimusicfactory.ai...")
    mp3_files = generate_music_batch(concept, count=4)
    log.info(f"Generated {len(mp3_files)} MP3 files")

    # Step 3: Merge all MP3s into one track
    log.info("=" * 60)
    log.info("STEP 3: Merging MP3 files...")
    merged_path = merge_mp3s(mp3_files, output_name=concept.track_name)
    log.info(f"Merged file: {merged_path}")

    # Step 4-7: Process (duration, thumbnail, video, upload)
    result = process_single_track(merged_path, concept=concept)
    return result


def cmd_login(args):
    """Open browser to log into aimusicfactory.ai and save session cookies.

    Launches a visible browser. Log in with Google, then close the browser.
    Cookies are saved automatically for future use.
    """
    from playwright.sync_api import sync_playwright

    state_file = AIMUSICFACTORY_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening browser for aimusicfactory.ai login...")
    log.info("Log in with your Google account, then close the browser window.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://aimusicfactory.ai", wait_until="networkidle", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Click 'Sign in with Google'")
        log.info("  2. Log into your Gmail account")
        log.info("  3. Wait until you see the main page (logged in)")
        log.info("  4. Close the browser window")
        log.info("=" * 60)

        # Wait for the user to close the browser
        try:
            page.wait_for_event("close", timeout=300_000)
        except Exception:
            pass

        # Save storage state (cookies + localStorage)
        context.storage_state(path=str(state_file))
        log.info(f"Session saved to: {state_file}")
        log.info("You can now run 'python main.py run' and it will use your account!")

        try:
            browser.close()
        except Exception:
            pass


def cmd_process(args):
    """Process existing MP3s from input/ folder.

    1. Find all MP3s in input/ folder
    2. Merge them into one track with pauses
    3. Generate concept, thumbnail, video, upload to YouTube
    """
    from modules.audio_merger import merge_mp3s
    from pipeline import process_single_track

    input_dir = Path(args.folder) if args.folder else INPUT_DIR
    mp3_files = sorted(input_dir.glob("*.mp3"))

    if not mp3_files:
        log.error(f"No MP3 files found in: {input_dir}")
        log.info(f"Put your MP3 files from aimusicfactory.ai in: {input_dir}")
        sys.exit(1)

    log.info(f"Found {len(mp3_files)} MP3 file(s) in {input_dir}:")
    for f in mp3_files:
        log.info(f"  - {f.name}")

    # Merge all MP3s
    log.info("=" * 60)
    log.info("MERGING MP3 FILES...")
    merged_path = merge_mp3s(mp3_files)
    log.info(f"Merged file: {merged_path}")

    # Process the merged track
    result = process_single_track(merged_path)

    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Done!")


def cmd_run(args):
    """Run full pipeline N times (generate music + merge + process + upload).

    Default: 4 clips. Each clip = generate music → merge → thumbnail → video → YouTube.
    """
    count = min(args.count, 8)
    log.info(f"Running full pipeline for {count} clip(s)...")

    total_errors = 0
    for i in range(1, count + 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"CLIP {i}/{count}")
        log.info(f"{'#' * 60}")
        try:
            result = _run_full_pipeline()
            if result["errors"]:
                total_errors += 1
                log.warning(f"Clip {i} had errors: {result['errors']}")
            else:
                log.info(f"Clip {i} completed: {result['concept']}")
        except Exception as e:
            total_errors += 1
            log.error(f"Clip {i} failed: {e}")

    log.info(f"\n{'=' * 60}")
    log.info(f"BATCH COMPLETE: {count - total_errors}/{count} clips successful")
    if total_errors:
        log.warning(f"{total_errors} clip(s) had errors")
        sys.exit(1)


def cmd_schedule(args):
    """Schedule 4 clips per day, uploaded to YouTube automatically.

    Default: runs at 08:00, 12:00, 16:00, 20:00 every day.
    Each run = generate music → merge → thumbnail → video → upload.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()

    # 4 clips per day: 07:00, 12:00, 16:00, 20:00
    hours = [7, 12, 16, 20]
    clips_per_day = args.clips or DEFAULT_CLIPS_PER_DAY

    if args.cron:
        # Custom cron - run clips_per_day times at that schedule
        parts = args.cron.split()
        if len(parts) != 5:
            log.error(f"Invalid cron: {args.cron}")
            sys.exit(1)
        minute, hour, day, month, day_of_week = parts
        scheduler.add_job(
            _run_full_pipeline,
            CronTrigger(
                minute=minute, hour=hour, day=day,
                month=month, day_of_week=day_of_week,
            ),
            id="music_pipeline",
            name="Music Pipeline",
        )
        log.info(f"Scheduled with cron: {args.cron}")
    else:
        # Default: spread clips across the day
        selected_hours = hours[:clips_per_day]
        for i, h in enumerate(selected_hours):
            scheduler.add_job(
                _run_full_pipeline,
                CronTrigger(hour=h, minute=0),
                id=f"music_pipeline_{i + 1}",
                name=f"Music Pipeline Clip {i + 1} ({h}:00)",
            )
        log.info(f"Scheduled {clips_per_day} clips per day at: {', '.join(f'{h}:00' for h in selected_hours)}")

    def shutdown(signum, frame):
        log.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Scheduler running. Press Ctrl+C to stop.")
    scheduler.start()


def main():
    parser = argparse.ArgumentParser(
        description="Afro House Music Pipeline — Full Automation",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # login - save aimusicfactory.ai cookies
    login_parser = subparsers.add_parser(
        "login",
        help="Log into aimusicfactory.ai (Google) and save cookies for automation",
    )
    login_parser.set_defaults(func=cmd_login)

    # process - merge existing MP3s from input/ and upload
    proc_parser = subparsers.add_parser(
        "process",
        help="Merge MP3s from input/ → thumbnail → video → YouTube",
    )
    proc_parser.add_argument(
        "--folder", type=str, default=None,
        help="Folder with MP3 files (default: input/)",
    )
    proc_parser.set_defaults(func=cmd_process)

    # run - full pipeline (generate music + merge + upload) × N
    run_parser = subparsers.add_parser(
        "run",
        help="Full pipeline: generate music → merge → thumbnail → video → YouTube",
    )
    run_parser.add_argument(
        "-n", "--count", type=int, default=DEFAULT_CLIPS_PER_DAY,
        help=f"Number of clips to create (default: {DEFAULT_CLIPS_PER_DAY})",
    )
    run_parser.set_defaults(func=cmd_run)

    # schedule - automatic 4 clips per day
    sched_parser = subparsers.add_parser(
        "schedule",
        help="Auto-schedule: 4 clips per day uploaded to YouTube",
    )
    sched_parser.add_argument(
        "--clips", type=int, default=None,
        help=f"Clips per day (default: {DEFAULT_CLIPS_PER_DAY})",
    )
    sched_parser.add_argument(
        "--cron", type=str, default=None,
        help='Custom cron (e.g. "0 10 * * *")',
    )
    sched_parser.set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
