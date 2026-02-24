#!/usr/bin/env python3
"""Afro House Music Pipeline — Full automation: generate, merge, thumbnail, video, upload."""

import argparse
import signal
import sys
from pathlib import Path

from config import SCHEDULE_CRON, INPUT_DIR, AIMUSICFACTORY_STATE_FILE, TIKTOK_COOKIE_FILE
from utils.logger import log

# Default: 4 clips per day
DEFAULT_CLIPS_PER_DAY = 4
# How many MP3s to generate per clip (3-4 generations × 2 = 6-8 MP3s)
MP3S_PER_CLIP = 8


def _run_full_pipeline(gen_count: int = 1):
    """Full pipeline: generate music on aimusicfactory → merge → thumbnail → video → upload.

    Args:
        gen_count: Number of times to hit Generate (each gives 2 MP3s).
    """
    from modules.music_generator import generate_music_batch
    from modules.audio_merger import merge_mp3s
    from modules.concept_generator import generate_concept
    from pipeline import process_single_track

    # Step 1: Generate concept first (for the music prompt)
    log.info("=" * 60)
    log.info("STEP 1: Generating Afro House concept...")
    concept = generate_concept()
    log.info(f"Track name: {concept.track_name}")

    # Step 2: Generate music on aimusicfactory.ai
    log.info("=" * 60)
    log.info(f"STEP 2: Generating music on aimusicfactory.ai ({gen_count} generation(s) = {gen_count * 2} MP3s)...")
    mp3_files = generate_music_batch(concept, count=gen_count)
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

    Uses the real Chrome browser (channel='chrome') to avoid Google blocking
    the login with 'This browser or app may not be secure'.
    Cookies are saved automatically for future use.
    """
    from playwright.sync_api import sync_playwright

    state_file = AIMUSICFACTORY_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for aimusicfactory.ai login...")
    log.info("Log in with your Google account, then close the browser window.")

    with sync_playwright() as p:
        # Use real Chrome to bypass Google's 'unsafe browser' detection
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.goto("https://aimusicfactory.ai", wait_until="networkidle", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Click 'Sign in with Google'")
        log.info("  2. Log into your Gmail account")
        log.info("  3. Wait until you see the main page (logged in)")
        log.info("  4. Come back here and press ENTER")
        log.info("=" * 60)

        # Wait for user to press Enter in terminal
        input("\n>>> Press ENTER here after you've logged in... ")

        # Save storage state (cookies + localStorage)
        context.storage_state(path=str(state_file))
        log.info(f"Session saved to: {state_file}")
        log.info("You can now run 'python main.py run' and it will use your account!")

        browser.close()


def cmd_tiktok_login(args):
    """Open browser to log into TikTok and save session cookies.

    Uses a real Chrome browser so TikTok does not block the login.
    Cookies are saved automatically for future uploads.
    """
    from playwright.sync_api import sync_playwright
    from utils.browser import save_cookies

    cookie_file = TIKTOK_COOKIE_FILE
    cookie_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for TikTok login...")
    log.info("Log in with your TikTok account, then come back here.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Log into your TikTok account")
        log.info("  2. Wait until you see your TikTok feed (logged in)")
        log.info("  3. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        save_cookies(context, cookie_file)
        log.info(f"TikTok cookies saved to: {cookie_file}")
        log.info("You can now run 'python main.py run' and TikTok uploads will work!")

        browser.close()


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


def cmd_download(args):
    """Download existing tracks from My Music on aimusicfactory.ai, then process them.

    Goes to My Music, finds the latest (or named) tracks, downloads MP3s,
    then merges → thumbnail → video → upload.
    """
    from modules.music_generator import download_existing_tracks
    from modules.audio_merger import merge_mp3s
    from modules.concept_generator import MusicConcept, generate_concept
    from pipeline import process_single_track

    track_name = args.name or ""
    max_cards = args.cards

    # Step 1: Download from My Music
    log.info("=" * 60)
    log.info("STEP 1: Downloading from My Music...")
    mp3_files = download_existing_tracks(track_name, max_cards=max_cards)
    log.info(f"Downloaded {len(mp3_files)} MP3 files")

    # Step 2: Merge
    log.info("=" * 60)
    log.info("STEP 2: Merging MP3 files...")
    merged_path = merge_mp3s(mp3_files, output_name=track_name or None)
    log.info(f"Merged file: {merged_path}")

    # Step 3-6: Process (concept, thumbnail, video, upload)
    # Use the track name from --name so AI doesn't pick a random name
    if track_name:
        concept = generate_concept(track_name=track_name)
    else:
        concept = None
    result = process_single_track(merged_path, concept=concept)

    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Done!")


def cmd_run(args):
    """Run full pipeline N times (generate music + merge + process + upload).

    Default: 1 clip. Each clip = 3 generations (6 MP3s) → merge → thumbnail → video → YouTube + TikTok.
    Use -n to create more clips in one run.
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


def cmd_reupload(args):
    """Re-upload an existing track to YouTube and TikTok (skip generation steps).

    Uses existing video/thumbnail files from output/ and regenerates only the
    concept metadata (title, description, tags) before uploading.

    Usage: python main.py reupload Tikasa
    """
    from pipeline import reupload_track

    track_name = args.name
    only = getattr(args, "only", None)
    log.info(f"Re-uploading existing track: {track_name}" + (f" (only {only})" if only else ""))
    result = reupload_track(track_name, only=only)

    if result["errors"]:
        log.warning(f"Completed with {len(result['errors'])} error(s)")
        sys.exit(1)
    else:
        log.info("Done!")


def cmd_schedule(args):
    """Schedule 4 clips per day, uploaded to YouTube + TikTok automatically.

    Default schedule:
      09:00 — 1 generate (2 MP3s) → 1 clip
      14:00 — 1 generate (2 MP3s) → 1 clip
      18:00 — 2 generates (4 MP3s) → 1 clip
      20:00 — 2 generates (4 MP3s) → 1 clip
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()

    # (hour, gen_count) — gen_count × 2 MP3s merged into one clip
    SCHEDULE_SLOTS = [
        (9,  1),   # 09:00 → 1 gen = 2 MP3s
        (14, 1),   # 14:00 → 1 gen = 2 MP3s
        (18, 2),   # 18:00 → 2 gen = 4 MP3s
        (20, 4),   # 20:00 → 4 gen = 8 MP3s
    ]

    if args.cron:
        # Custom cron - run with default gen_count=1
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
        # Default schedule with variable generation counts
        clips_per_day = args.clips or len(SCHEDULE_SLOTS)
        selected_slots = SCHEDULE_SLOTS[:clips_per_day]
        for i, (hour, gen_count) in enumerate(selected_slots):
            scheduler.add_job(
                _run_full_pipeline,
                CronTrigger(hour=hour, minute=0),
                kwargs={"gen_count": gen_count},
                id=f"music_pipeline_{i + 1}",
                name=f"Clip {i + 1} ({hour}:00, {gen_count} gen)",
            )
        schedule_desc = ", ".join(f"{h}:00 ({g} gen)" for h, g in selected_slots)
        log.info(f"Scheduled {len(selected_slots)} clips per day: {schedule_desc}")

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

    # tiktok-login - save TikTok cookies
    tiktok_login_parser = subparsers.add_parser(
        "tiktok-login",
        help="Log into TikTok and save cookies for automated uploads",
    )
    tiktok_login_parser.set_defaults(func=cmd_tiktok_login)

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

    # download - grab existing tracks from My Music and process
    dl_parser = subparsers.add_parser(
        "download",
        help="Download existing tracks from My Music → merge → thumbnail → video → YouTube",
    )
    dl_parser.add_argument(
        "--name", type=str, default=None,
        help="Track name to search for (default: grab latest)",
    )
    dl_parser.add_argument(
        "--cards", type=int, default=4,
        help="Max number of cards to download from (default: 4)",
    )
    dl_parser.set_defaults(func=cmd_download)

    # reupload - re-upload existing track (skip generation, just upload)
    reupload_parser = subparsers.add_parser(
        "reupload",
        help="Re-upload existing track to YouTube + TikTok (skip generation)",
    )
    reupload_parser.add_argument(
        "name", type=str,
        help="Track name (e.g. Tikasa) — must match files in output/",
    )
    reupload_parser.add_argument(
        "--only", choices=["youtube", "tiktok"],
        help="Upload to only one platform (default: both)",
    )
    reupload_parser.set_defaults(func=cmd_reupload)

    # run - full pipeline (generate music + merge + upload) × N
    run_parser = subparsers.add_parser(
        "run",
        help="Full pipeline: generate music → merge → thumbnail → video → YouTube",
    )
    run_parser.add_argument(
        "-n", "--count", type=int, default=1,
        help="Number of clips to create (default: 1)",
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
