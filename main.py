#!/usr/bin/env python3
"""Afro House Music Pipeline — Full automation: generate, merge, thumbnail, video, upload."""

import argparse
import os
import signal
import sys
from pathlib import Path

from config import (
    SCHEDULE_CRON, INPUT_DIR, AIMUSICFACTORY_STATE_FILE, TIKTOK_COOKIE_FILE,
    SUNO_STATE_FILE, UDIO_STATE_FILE, TUNECORE_STATE_FILE, SOUNDCLOUD_STATE_FILE,
    MUSIC_PLATFORM, SONGS_PER_CLIP,
)
from utils.logger import log

# Supported music platforms
PLATFORMS = ["aimusicfactory", "suno", "udio"]

# Default: 3 clips per day (one per scheduled slot)
DEFAULT_CLIPS_PER_DAY = 3
# Total MP3s per day: 2 + 4 + 8 = 14 MP3s → 3 merged clips
MP3S_PER_CLIP = 8


def _get_music_generator(platform: str):
    """Import and return the generate_music_batch function for the given platform."""
    if platform == "suno":
        from modules.suno_generator import generate_music_batch
    elif platform == "udio":
        from modules.udio_generator import generate_music_batch
    else:
        from modules.music_generator import generate_music_batch
    return generate_music_batch


def _run_full_pipeline(gen_count: int = 1, platform: str = None, songs: int = None,
                       genre: str = "", music_style: str = "", thumbnail_style: str = ""):
    """Full pipeline: generate music → merge → thumbnail → video → upload.

    Args:
        gen_count: Number of times to hit Generate (each gives 2 MP3s).
        platform: Music platform — "aimusicfactory", "suno", or "udio".
        songs: Total number of songs to generate (2, 4, 6, 8). Overrides gen_count.
        genre: Music genre (e.g. "Afro House", "Lo-Fi"). Falls back to config.
        music_style: Custom music style prompt. Falls back to config or default.
        thumbnail_style: Custom thumbnail prompt. Falls back to config or default.
    """
    from modules.audio_merger import merge_mp3s
    from modules.concept_generator import generate_concept
    from pipeline import process_single_track

    platform = platform or MUSIC_PLATFORM
    if songs:
        gen_count = max(1, songs // 2)  # Each generation = 2 songs

    generate_music_batch = _get_music_generator(platform)

    # Step 1: Generate concept first (for the music prompt)
    log.info("=" * 60)
    log.info(f"STEP 1: Generating {genre or 'music'} concept...")
    concept = generate_concept(genre=genre, music_style=music_style,
                               thumbnail_style=thumbnail_style)
    log.info(f"Track name: {concept.track_name}")

    # Step 2: Generate music
    log.info("=" * 60)
    log.info(f"STEP 2: Generating music on {platform} ({gen_count} generation(s) = {gen_count * 2} songs)...")
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


def cmd_youtube_login(args):
    """Open browser to log into YouTube Studio and save session cookies.

    These cookies are needed for self-certification (monetization).
    The regular YouTube upload uses OAuth (separate token), but YouTube Studio
    features like self-certification require browser cookies.
    """
    from playwright.sync_api import sync_playwright
    from utils.browser import save_cookies
    from config import YOUTUBE_COOKIE_FILE

    cookie_file = YOUTUBE_COOKIE_FILE
    cookie_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for YouTube Studio login...")
    log.info("Log in with your YouTube account, then come back here.")

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
        page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Log into your YouTube/Google account")
        log.info("  2. Wait until you see YouTube Studio dashboard")
        log.info("  3. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        save_cookies(context, cookie_file)
        log.info(f"YouTube Studio cookies saved to: {cookie_file}")
        log.info("Self-certification will now work automatically!")

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


def cmd_tunecore_login(args):
    """Open browser to log into TuneCore and save session state.

    These cookies are needed for automated single/album uploads to TuneCore.
    """
    from playwright.sync_api import sync_playwright

    state_file = TUNECORE_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for TuneCore login...")
    log.info("Log in with your TuneCore account, then come back here.")

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
        page.goto("https://web.tunecore.com/login?check=1", wait_until="networkidle", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Log into your TuneCore account")
        log.info("  2. Wait until you see the TuneCore dashboard")
        log.info("  3. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        context.storage_state(path=str(state_file))
        log.info(f"TuneCore session saved to: {state_file}")
        log.info("You can now run the pipeline and TuneCore uploads will work!")

        browser.close()


def cmd_tunecore_continue(args):
    """Continue an existing TuneCore draft release (no WAV/cover needed).

    Finds the draft by name on TuneCore dashboard and fills in track details.
    Usage: python main.py tunecore-continue "Zyphara Nelu"
    """
    from modules.tunecore_uploader import continue_tunecore_draft

    track_name = args.name
    log.info(f"Continuing TuneCore draft: {track_name}")
    result = continue_tunecore_draft(track_name)
    if result:
        log.info(f"Done! Result: {result}")
    else:
        log.error("Failed — check logs and screenshots in output/")
        sys.exit(1)


def cmd_tunecore_latest(args):
    """Find the most recently created thumbnail/cover in output/ and upload to TuneCore.

    Starts from the latest thumbnail or cover art, then finds the matching WAV.
    Usage: python main.py tunecore-latest
    """
    from config import OUTPUT_DIR
    from modules.tunecore_uploader import upload_to_tunecore
    from modules.concept_generator import MusicConcept

    # Find the latest cover or thumbnail (this is the starting point)
    image_files = sorted(
        list(OUTPUT_DIR.glob("*_cover.jpg")) + list(OUTPUT_DIR.glob("*_cover.png"))
        + list(OUTPUT_DIR.glob("*_thumbnail.jpg")) + list(OUTPUT_DIR.glob("*_thumbnail.png")),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not image_files:
        log.error(f"No cover art or thumbnails found in {OUTPUT_DIR}")
        sys.exit(1)

    cover_path = image_files[0]
    log.info(f"Latest image: {cover_path.name}")

    # Derive track name from image filename
    # e.g. "FailTest_thumbnail.jpg" -> "FailTest", "Zanu_cover.jpg" -> "Zanu"
    stem = cover_path.stem
    for tag in ("_thumbnail", "_cover"):
        stem = stem.replace(tag, "")
    track_name = stem.replace("_", " ")
    log.info(f"Track name: {track_name}")

    # Find matching WAV file
    wav_path = None
    for name_variant in [stem, track_name.replace(" ", "_")]:
        candidate = OUTPUT_DIR / f"{name_variant}.wav"
        if candidate.exists():
            wav_path = candidate
            break

    # If no matching WAV, use the latest WAV as fallback
    if not wav_path:
        wav_files = sorted(OUTPUT_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
        if wav_files:
            wav_path = wav_files[0]
            log.warning(f"No WAV for '{track_name}', using latest: {wav_path.name}")

    if not wav_path:
        log.error(f"No WAV files found in {OUTPUT_DIR}")
        sys.exit(1)

    log.info(f"WAV file: {wav_path.name}")
    log.info(f"Cover art: {cover_path.name}")

    # Build a minimal MusicConcept for the upload
    concept = MusicConcept(
        track_name=track_name,
        genre="Afro House",
        mood="",
        description="",
        music_prompt="",
        hashtags=[],
        thumbnail_prompt="",
        youtube_title=track_name,
        youtube_description="",
        youtube_tags=[],
        tiktok_caption="",
    )

    result = upload_to_tunecore(wav_path, cover_path, concept)
    if result:
        log.info(f"Done! TuneCore result: {result}")
    else:
        log.error("TuneCore upload failed — check logs and screenshots in output/")
        sys.exit(1)


def cmd_soundcloud_login(args):
    """Open browser to log into SoundCloud and save session state.

    These cookies are needed for automated track uploads to SoundCloud.
    """
    from playwright.sync_api import sync_playwright

    state_file = SOUNDCLOUD_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for SoundCloud login...")
    log.info("Log in with your SoundCloud account, then come back here.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        # Close any blank tabs that Chrome opens by default
        for existing_page in context.pages:
            existing_page.close()

        page = context.new_page()
        page.goto("https://soundcloud.com", wait_until="commit", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Click 'Sign in' on SoundCloud")
        log.info("  2. Log into your account (Google, Facebook, email, etc.)")
        log.info("  3. Wait until you see the SoundCloud feed (logged in)")
        log.info("  4. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        context.storage_state(path=str(state_file))
        log.info(f"SoundCloud session saved to: {state_file}")
        log.info("You can now run the pipeline and SoundCloud uploads will work!")

        browser.close()


def cmd_suno_login(args):
    """Open browser to log into suno.com and save session state."""
    from playwright.sync_api import sync_playwright

    state_file = SUNO_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for Suno login...")
    log.info("Log in with your account, then close the browser window.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.goto("https://suno.com", wait_until="networkidle", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Click 'Sign In' on suno.com")
        log.info("  2. Log into your account (Google, Discord, etc.)")
        log.info("  3. Wait until you see the main page (logged in)")
        log.info("  4. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        context.storage_state(path=str(state_file))
        log.info(f"Suno session saved to: {state_file}")
        log.info("You can now run 'python main.py run --platform suno' and it will use your account!")
        browser.close()


def cmd_udio_login(args):
    """Open browser to log into udio.com and save session state."""
    from playwright.sync_api import sync_playwright

    state_file = UDIO_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening Chrome browser for Udio login...")
    log.info("Log in with your account, then close the browser window.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.goto("https://www.udio.com", wait_until="networkidle", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Click 'Sign In' on udio.com")
        log.info("  2. Log into your account (Google, Discord, etc.)")
        log.info("  3. Wait until you see the main page (logged in)")
        log.info("  4. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        context.storage_state(path=str(state_file))
        log.info(f"Udio session saved to: {state_file}")
        log.info("You can now run 'python main.py run --platform udio' and it will use your account!")
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

    Default: 1 clip. Each clip = 1 generation (2 MP3s) → merge → thumbnail → video → YouTube + TikTok.
    Use -n to create more clips in one run.
    Use --platform to choose: aimusicfactory, suno, udio
    Use --songs to choose how many songs per clip: 2, 4, 6, 8
    Use --gens to control how many generations per clip (each = 2 MP3s).
    """
    count = min(args.count, 8)
    platform = args.platform or MUSIC_PLATFORM
    songs = args.songs or SONGS_PER_CLIP
    gen_count = args.gens
    log.info(f"Running full pipeline for {count} clip(s) on {platform} ({songs} songs each, {gen_count} gen(s))...")

    total_errors = 0
    for i in range(1, count + 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"CLIP {i}/{count}")
        log.info(f"{'#' * 60}")
        try:
            result = _run_full_pipeline(gen_count=gen_count, platform=platform, songs=songs)
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


def cmd_autostart(args):
    """Place a silent VBS launcher in the Windows Startup folder.

    The launcher runs 'python main.py schedule' when the user logs in.
    No administrator privileges required — uses the per-user Startup folder.
    """
    import platform as plat
    import subprocess

    if plat.system() != "Windows":
        log.error("Autostart is only supported on Windows")
        log.info("On Linux/macOS, use crontab or systemd instead.")
        sys.exit(1)

    python = sys.executable
    project_dir = str(Path(__file__).parent.resolve())
    startup_dir = Path(os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    ))
    vbs_name = "music_pipeline_schedule_silent.vbs"
    vbs_path = startup_dir / vbs_name
    # Legacy paths from old Task Scheduler approach
    legacy_task = "MusicPipelineScheduler"
    legacy_vbs = Path(project_dir) / "schedule_silent.vbs"

    def _cleanup_legacy():
        """Remove old Task Scheduler task and project-dir VBS if present."""
        from utils.subprocess_utils import _no_window_kwargs
        subprocess.run(
            ["schtasks", "/Delete", "/TN", legacy_task, "/F"],
            capture_output=True, text=True,
            **_no_window_kwargs(),
        )
        if legacy_vbs.exists():
            legacy_vbs.unlink()
            log.info("Removed legacy schedule_silent.vbs from project folder")

    if args.remove:
        if vbs_path.exists():
            vbs_path.unlink()
            log.info(f"Removed autostart launcher: {vbs_path}")
        else:
            log.info("No autostart launcher found to remove")
        _cleanup_legacy()
        return

    if not startup_dir.is_dir():
        log.error(f"Startup folder not found: {startup_dir}")
        sys.exit(1)

    _cleanup_legacy()

    # Build a silent VBS launcher so no CMD/PowerShell window appears
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{project_dir}"\n'
    )
    # Activate venv if it exists, then run the scheduler (PowerShell, no CMD)
    sq = "'"  # single quote — can't use backslash escapes inside f-strings
    venv_activate = Path(project_dir) / "venv" / "Scripts" / "Activate.ps1"
    venv2_activate = Path(project_dir) / ".venv" / "Scripts" / "Activate.ps1"
    if venv_activate.exists():
        vbs_content += f'WshShell.Run "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""& venv\\Scripts\\Activate.ps1; & {sq}{python}{sq} main.py schedule""", 0, False\n'
    elif venv2_activate.exists():
        vbs_content += f'WshShell.Run "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""& .venv\\Scripts\\Activate.ps1; & {sq}{python}{sq} main.py schedule""", 0, False\n'
    else:
        vbs_content += f'WshShell.Run "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""& {sq}{python}{sq} main.py schedule""", 0, False\n'
    vbs_path.write_text(vbs_content, encoding="utf-8")

    log.info(f"Autostart launcher installed: {vbs_path}")
    log.info("The scheduler will run SILENTLY (no CMD/PowerShell window).")
    log.info("It starts automatically when you log in — no admin required.")
    log.info("")
    log.info(f"To verify: check your Startup folder")
    log.info("To remove: python main.py autostart --remove")


def cmd_schedule(args):
    """Schedule 4 clips per day, uploaded to YouTube + TikTok automatically.

    Default schedule (Europe/Bucharest timezone):
      10:40 — 1 generate (2 MP3s) → 1 clip
      14:00 — 1 generate (2 MP3s) → 1 clip
      18:00 — 2 generates (4 MP3s) → 1 clip
      20:00 — 4 generates (8 MP3s) → 1 clip

    Uses misfire_grace_time=3600 so jobs still run even if the PC
    wakes from sleep up to 1 hour late.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.events import EVENT_JOB_MISSED, EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

    # ── Prevent multiple scheduler instances running at the same time ──
    lock_path = Path(__file__).parent / ".scheduler.lock"
    _lock_fd = None
    import platform as plat
    if plat.system() == "Windows":
        import msvcrt
        try:
            _lock_fd = open(lock_path, "w")
            msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            _lock_fd.write(str(os.getpid()))
            _lock_fd.flush()
        except (OSError, IOError):
            log.error("Scheduler-ul DEJA ruleaza intr-o alta fereastra!")
            log.error("Inchide cealalta fereastra (CMD sau PowerShell) si incearca din nou.")
            if _lock_fd:
                _lock_fd.close()
            sys.exit(1)
    else:
        import fcntl
        try:
            _lock_fd = open(lock_path, "w")
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_fd.write(str(os.getpid()))
            _lock_fd.flush()
        except (OSError, IOError):
            log.error("Scheduler-ul DEJA ruleaza intr-o alta fereastra!")
            log.error("Inchide cealalta fereastra si incearca din nou.")
            if _lock_fd:
                _lock_fd.close()
            sys.exit(1)

    TIMEZONE = "Europe/Bucharest"

    # Log scheduler events (missed jobs, errors, successes)
    def _job_listener(event):
        if event.code == EVENT_JOB_MISSED:
            log.warning(f"Job MISSED (ran late): {event.job_id} — will retry next window")
        elif event.code == EVENT_JOB_ERROR:
            log.error(f"Job ERROR: {event.job_id} — {event.exception}")
        elif event.code == EVENT_JOB_EXECUTED:
            log.info(f"Job DONE: {event.job_id}")

    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_listener(_job_listener, EVENT_JOB_MISSED | EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # (hour, minute, gen_count) — gen_count × 2 MP3s merged into one clip
    SCHEDULE_SLOTS = [
        (13, 0,  1),   # 13:00 → 1 gen = 2 MP3s (ready ~13:15, before 15:00 peak)
        (16, 0,  2),   # 16:00 → 2 gen = 4 MP3s (ready ~16:15, before 18:00 peak)
        (19, 0,  4),   # 19:00 → 4 gen = 8 MP3s (ready ~19:15, before 21:00 peak)
    ]

    # 1 hour grace — if PC wakes from sleep within 1h, the job still fires
    MISFIRE_GRACE = 3600

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
                timezone=TIMEZONE,
            ),
            id="music_pipeline",
            name="Music Pipeline",
            misfire_grace_time=MISFIRE_GRACE,
            coalesce=True,
        )
        log.info(f"Scheduled with cron: {args.cron}")
    else:
        # Default schedule with variable generation counts
        clips_per_day = args.clips or len(SCHEDULE_SLOTS)
        selected_slots = SCHEDULE_SLOTS[:clips_per_day]
        for i, (hour, minute, gen_count) in enumerate(selected_slots):
            scheduler.add_job(
                _run_full_pipeline,
                CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE),
                kwargs={"gen_count": gen_count},
                id=f"music_pipeline_{i + 1}",
                name=f"Clip {i + 1} ({hour}:{minute:02d}, {gen_count} gen)",
                misfire_grace_time=MISFIRE_GRACE,
                coalesce=True,
            )
        schedule_desc = ", ".join(f"{h}:{m:02d} ({g} gen)" for h, m, g in selected_slots)
        log.info(f"Scheduled {len(selected_slots)} clips per day: {schedule_desc}")
        log.info(f"Timezone: {TIMEZONE} | Misfire grace: {MISFIRE_GRACE}s")

    def shutdown(signum, frame):
        log.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        # Release lock file
        if _lock_fd:
            _lock_fd.close()
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass
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

    # youtube-login - save YouTube Studio cookies
    youtube_login_parser = subparsers.add_parser(
        "youtube-login",
        help="Log into YouTube Studio and save cookies for self-certification",
    )
    youtube_login_parser.set_defaults(func=cmd_youtube_login)

    # tiktok-login - save TikTok cookies
    tiktok_login_parser = subparsers.add_parser(
        "tiktok-login",
        help="Log into TikTok and save cookies for automated uploads",
    )
    tiktok_login_parser.set_defaults(func=cmd_tiktok_login)

    # tunecore-login - save TuneCore session state
    tunecore_login_parser = subparsers.add_parser(
        "tunecore-login",
        help="Log into TuneCore and save session for automated uploads",
    )
    tunecore_login_parser.set_defaults(func=cmd_tunecore_login)

    # tunecore-continue - continue an existing TuneCore draft
    tc_cont_parser = subparsers.add_parser(
        "tunecore-continue",
        help="Continue filling out an existing TuneCore draft (no WAV needed)",
    )
    tc_cont_parser.add_argument(
        "name", type=str,
        help="Track name on TuneCore (e.g. 'Zyphara Nelu')",
    )
    tc_cont_parser.set_defaults(func=cmd_tunecore_continue)

    # tunecore-latest - auto-find latest WAV + cover and upload
    subparsers.add_parser(
        "tunecore-latest",
        help="Find latest WAV + cover art in output/ and upload to TuneCore",
    ).set_defaults(func=cmd_tunecore_latest)

    # soundcloud-login - save SoundCloud session state
    soundcloud_login_parser = subparsers.add_parser(
        "soundcloud-login",
        help="Log into SoundCloud and save session for automated uploads",
    )
    soundcloud_login_parser.set_defaults(func=cmd_soundcloud_login)

    # suno-login - save Suno session state
    suno_login_parser = subparsers.add_parser(
        "suno-login",
        help="Log into suno.com and save session for automation",
    )
    suno_login_parser.set_defaults(func=cmd_suno_login)

    # udio-login - save Udio session state
    udio_login_parser = subparsers.add_parser(
        "udio-login",
        help="Log into udio.com and save session for automation",
    )
    udio_login_parser.set_defaults(func=cmd_udio_login)

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
        "--only", choices=["youtube", "tiktok", "tunecore", "soundcloud"],
        help="Upload to only one platform (default: all)",
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
    run_parser.add_argument(
        "--platform", choices=PLATFORMS, default=None,
        help=f"Music platform: {', '.join(PLATFORMS)} (default: from .env or aimusicfactory)",
    )
    run_parser.add_argument(
        "--songs", type=int, choices=[2, 4, 6, 8], default=None,
        help="Number of songs per clip to generate and merge (default: from .env or 2)",
    )
    run_parser.add_argument(
        "-g", "--gens", type=int, default=1,
        help="Generations per clip — each generation = 2 MP3s (default: 1)",
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

    # autostart - start scheduler automatically on Windows login
    autostart_parser = subparsers.add_parser(
        "autostart",
        help="Auto-start the scheduler on Windows login (Startup folder, no admin needed)",
    )
    autostart_parser.add_argument(
        "--remove", action="store_true",
        help="Remove the autostart task",
    )
    autostart_parser.set_defaults(func=cmd_autostart)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
