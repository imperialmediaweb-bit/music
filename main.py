#!/usr/bin/env python3
"""Afro House Music Pipeline — Merge MP3s, Thumbnail, Video, YouTube Upload."""

import argparse
import signal
import sys
from pathlib import Path

from config import SCHEDULE_CRON, INPUT_DIR
from utils.logger import log


def cmd_process(args):
    """Main workflow:

    1. Find all MP3s in input/ folder (from aimusicfactory.ai downloads)
    2. Merge them into one track with pauses between each
    3. Detect duration
    4. Generate Afro House concept (name, description, tags)
    5. Generate African mask thumbnail with track name
    6. Create YouTube video (16:9) + TikTok video (9:16)
    7. Upload to YouTube with title, description, tags, thumbnail
    8. Upload to TikTok
    """
    from modules.audio_merger import merge_mp3s
    from pipeline import process_single_track

    # Find MP3 files
    input_dir = Path(args.folder) if args.folder else INPUT_DIR
    mp3_files = sorted(input_dir.glob("*.mp3"))

    if not mp3_files:
        log.error(f"No MP3 files found in: {input_dir}")
        log.info(f"Put your MP3 files from aimusicfactory.ai in: {input_dir}")
        sys.exit(1)

    log.info(f"Found {len(mp3_files)} MP3 file(s) in {input_dir}:")
    for f in mp3_files:
        log.info(f"  - {f.name}")

    # Step 1: Merge all MP3s into one track
    log.info("=" * 60)
    log.info("MERGING MP3 FILES...")
    try:
        merged_path = merge_mp3s(mp3_files)
        log.info(f"Merged file: {merged_path}")
    except Exception as e:
        log.error(f"Merge failed: {e}")
        sys.exit(1)

    # Step 2: Process the merged track (thumbnail, video, upload)
    result = process_single_track(merged_path)

    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Done!")


def cmd_single(args):
    """Process a single MP3 file (already merged/compiled)."""
    from pipeline import process_single_track

    mp3_path = Path(args.file)
    if not mp3_path.exists():
        log.error(f"File not found: {mp3_path}")
        sys.exit(1)

    log.info(f"Processing: {mp3_path.name}")
    result = process_single_track(mp3_path)

    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Done!")


def cmd_schedule(args):
    """Run the pipeline on a cron schedule."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from modules.audio_merger import merge_mp3s
    from pipeline import process_single_track

    cron_expr = args.cron or SCHEDULE_CRON
    parts = cron_expr.split()
    if len(parts) != 5:
        log.error(f"Invalid cron expression: {cron_expr} (expected 5 fields)")
        sys.exit(1)

    minute, hour, day, month, day_of_week = parts

    def scheduled_job():
        mp3_files = sorted(INPUT_DIR.glob("*.mp3"))
        if mp3_files:
            merged = merge_mp3s(mp3_files)
            process_single_track(merged)
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
        description="Afro House Music Pipeline — Merge, Thumbnail, Video, Upload",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # process command - main workflow (merge MP3s → process → upload)
    proc_parser = subparsers.add_parser(
        "process",
        help="Merge MP3s from input/ folder → thumbnail → video → YouTube upload",
    )
    proc_parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="Folder with MP3 files (default: input/)",
    )
    proc_parser.set_defaults(func=cmd_process)

    # single command - process one already-merged MP3
    single_parser = subparsers.add_parser(
        "single",
        help="Process a single MP3 file (already merged)",
    )
    single_parser.add_argument("file", help="Path to MP3 file")
    single_parser.set_defaults(func=cmd_single)

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
