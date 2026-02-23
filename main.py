#!/usr/bin/env python3
"""Music Content Automation Pipeline — CLI + Scheduler."""

import argparse
import signal
import sys
from pathlib import Path

from config import SCHEDULE_CRON, INPUT_DIR
from utils.logger import log


def cmd_run(args):
    """Run the full pipeline for N tracks (generate music + process)."""
    from pipeline import run_pipeline

    count = min(args.count, 8)
    log.info(f"Starting pipeline for {count} track(s)...")

    total_errors = 0
    for i in range(1, count + 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"TRACK {i}/{count}")
        log.info(f"{'#' * 60}")
        result = run_pipeline()
        if result["errors"]:
            total_errors += 1
            log.warning(f"Track {i} had errors: {result['errors']}")
        else:
            log.info(f"Track {i} completed: {result['concept']}")

    log.info(f"\n{'=' * 60}")
    log.info(f"BATCH COMPLETE: {count - total_errors}/{count} tracks successful")
    if total_errors:
        log.warning(f"{total_errors} track(s) had errors")
        sys.exit(1)


def cmd_process(args):
    """Process existing MP3 files from input/ folder."""
    from pipeline import process_existing_files

    # Find MP3 files
    input_dir = Path(args.folder) if args.folder else INPUT_DIR
    mp3_files = sorted(input_dir.glob("*.mp3"))

    if not mp3_files:
        log.error(f"No MP3 files found in: {input_dir}")
        log.info(f"Put your MP3 files in: {input_dir}")
        sys.exit(1)

    # Limit to max 8
    if len(mp3_files) > 8:
        log.warning(f"Found {len(mp3_files)} files, processing first 8")
        mp3_files = mp3_files[:8]

    log.info(f"Found {len(mp3_files)} MP3 file(s) in {input_dir}:")
    for f in mp3_files:
        log.info(f"  - {f.name}")

    results = process_existing_files(mp3_files)

    total = len(results)
    errors = sum(1 for r in results if r["errors"])
    log.info(f"\n{'=' * 60}")
    log.info(f"BATCH COMPLETE: {total - errors}/{total} tracks successful")
    if errors:
        log.warning(f"{errors} track(s) had errors")
        sys.exit(1)


def cmd_schedule(args):
    """Run the pipeline on a cron schedule."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from pipeline import run_pipeline

    cron_expr = args.cron or SCHEDULE_CRON
    parts = cron_expr.split()
    if len(parts) != 5:
        log.error(f"Invalid cron expression: {cron_expr} (expected 5 fields)")
        sys.exit(1)

    minute, hour, day, month, day_of_week = parts

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        ),
        id="music_pipeline",
        name="Music Content Pipeline",
    )

    # Graceful shutdown
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
        description="Music Content Automation Pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command - full pipeline (generate music + process)
    run_parser = subparsers.add_parser("run", help="Generate music + process (full pipeline)")
    run_parser.add_argument(
        "-n", "--count",
        type=int,
        default=1,
        help="Number of tracks to generate (max 8, default 1)",
    )
    run_parser.set_defaults(func=cmd_run)

    # process command - process existing MP3 files
    proc_parser = subparsers.add_parser(
        "process",
        help="Process existing MP3 files from input/ folder",
    )
    proc_parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="Folder with MP3 files (default: input/)",
    )
    proc_parser.set_defaults(func=cmd_process)

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
