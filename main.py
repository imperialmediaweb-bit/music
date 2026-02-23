#!/usr/bin/env python3
"""Music Content Automation Pipeline — CLI + Scheduler."""

import argparse
import signal
import sys
from pathlib import Path

from config import SCHEDULE_CRON, INPUT_DIR
from utils.logger import log


def cmd_process(args):
    """Process a compiled MP3 from D:\\music or input/ folder.

    Workflow:
    1. Generate 8 tracks on aimusicfactory.ai (manual)
    2. Combine them in CapCut with pauses
    3. Export final MP3 to D:\\music
    4. Run: python main.py process
    5. Pipeline detects duration, generates concept/thumbnail/video, uploads to YouTube
    """
    from pipeline import process_single_track

    # Find the MP3 file
    if args.file:
        mp3_path = Path(args.file)
        if not mp3_path.exists():
            log.error(f"File not found: {mp3_path}")
            sys.exit(1)
    else:
        # Look for MP3 files in input/ or current directory
        search_dirs = [INPUT_DIR, Path(".")]
        mp3_path = None
        for d in search_dirs:
            mp3_files = sorted(d.glob("*.mp3"), key=lambda f: f.stat().st_mtime, reverse=True)
            if mp3_files:
                mp3_path = mp3_files[0]  # Most recent MP3
                break

        if not mp3_path:
            log.error("No MP3 file found!")
            log.info("Usage:")
            log.info("  python main.py process track.mp3")
            log.info("  python main.py process  (auto-finds newest MP3 in input/)")
            sys.exit(1)

    log.info(f"Processing: {mp3_path.name}")
    result = process_single_track(mp3_path)

    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Done!")


def cmd_batch(args):
    """Process multiple MP3 files (each one = separate YouTube upload)."""
    from pipeline import process_single_track

    input_dir = Path(args.folder) if args.folder else INPUT_DIR
    mp3_files = sorted(input_dir.glob("*.mp3"))

    if not mp3_files:
        log.error(f"No MP3 files found in: {input_dir}")
        sys.exit(1)

    if len(mp3_files) > 8:
        log.warning(f"Found {len(mp3_files)} files, processing first 8")
        mp3_files = mp3_files[:8]

    log.info(f"Found {len(mp3_files)} MP3 file(s):")
    for f in mp3_files:
        log.info(f"  - {f.name}")

    total_errors = 0
    for i, mp3 in enumerate(mp3_files, 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"TRACK {i}/{len(mp3_files)}: {mp3.name}")
        log.info(f"{'#' * 60}")
        result = process_single_track(mp3)
        if result["errors"]:
            total_errors += 1

    log.info(f"\n{'=' * 60}")
    log.info(f"BATCH COMPLETE: {len(mp3_files) - total_errors}/{len(mp3_files)} successful")
    if total_errors:
        sys.exit(1)


def cmd_schedule(args):
    """Run the pipeline on a cron schedule."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from pipeline import process_single_track

    cron_expr = args.cron or SCHEDULE_CRON
    parts = cron_expr.split()
    if len(parts) != 5:
        log.error(f"Invalid cron expression: {cron_expr} (expected 5 fields)")
        sys.exit(1)

    minute, hour, day, month, day_of_week = parts

    def scheduled_job():
        mp3_files = sorted(INPUT_DIR.glob("*.mp3"), key=lambda f: f.stat().st_mtime, reverse=True)
        if mp3_files:
            process_single_track(mp3_files[0])
        else:
            log.warning(f"No MP3 files in {INPUT_DIR}")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        scheduled_job,
        CronTrigger(
            minute=minute, hour=hour, day=day,
            month=month, day_of_week=day_of_week,
        ),
        id="music_pipeline",
        name="Music Content Pipeline",
    )

    def shutdown(signum, frame):
        log.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info(f"Scheduler started with cron: {cron_expr}")
    log.info("Press Ctrl+C to stop")
    scheduler.start()


def main():
    parser = argparse.ArgumentParser(
        description="Afro House Music Pipeline — Thumbnail, Video, YouTube Upload",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # process command - main workflow (one compiled MP3 → YouTube)
    proc_parser = subparsers.add_parser(
        "process",
        help="Process a compiled MP3 → generate concept, thumbnail, video, upload to YouTube",
    )
    proc_parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to MP3 file (default: newest MP3 in input/)",
    )
    proc_parser.set_defaults(func=cmd_process)

    # batch command - multiple MP3s
    batch_parser = subparsers.add_parser(
        "batch",
        help="Process multiple MP3 files from input/ folder",
    )
    batch_parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="Folder with MP3 files (default: input/)",
    )
    batch_parser.set_defaults(func=cmd_batch)

    # schedule command
    sched_parser = subparsers.add_parser("schedule", help="Run pipeline on schedule")
    sched_parser.add_argument(
        "--cron",
        type=str,
        default=None,
        help='Cron expression (5 fields, e.g. "0 10 * * *")',
    )
    sched_parser.set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
