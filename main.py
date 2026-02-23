#!/usr/bin/env python3
"""Music Content Automation Pipeline — CLI + Scheduler."""

import argparse
import signal
import sys

from config import SCHEDULE_CRON
from utils.logger import log


def cmd_run(args):
    """Run the pipeline once."""
    from pipeline import run_pipeline

    log.info("Starting single pipeline run...")
    result = run_pipeline()
    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Completed successfully")


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

    # run command
    run_parser = subparsers.add_parser("run", help="Run pipeline once")
    run_parser.set_defaults(func=cmd_run)

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
