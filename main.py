#!/usr/bin/env python3
"""Afro House Music Pipeline — Full automation: generate, merge, thumbnail, video, upload."""

import argparse
import os
import signal
import sys
from pathlib import Path

# Extract --profile from sys.argv BEFORE importing config, so config.py picks
# up the correct profile-specific .env.<profile> file. Removing the flag from
# sys.argv keeps argparse unaware of it (no declaration needed on every
# subparser, and no risk of breaking existing commands).
_idx = 0
while _idx < len(sys.argv):
    _arg = sys.argv[_idx]
    if _arg == "--profile" and _idx + 1 < len(sys.argv):
        os.environ["LUTH_PROFILE"] = sys.argv[_idx + 1]
        del sys.argv[_idx : _idx + 2]
        break
    if _arg.startswith("--profile="):
        os.environ["LUTH_PROFILE"] = _arg.split("=", 1)[1]
        del sys.argv[_idx]
        break
    _idx += 1

from config import (
    SCHEDULE_CRON, INPUT_DIR, AIMUSICFACTORY_STATE_FILE, TIKTOK_COOKIE_FILE,
    SUNO_STATE_FILE, UDIO_STATE_FILE, TUNECORE_STATE_FILE, SOUNDCLOUD_STATE_FILE,
    BANDCAMP_STATE_FILE, MUSIC_PLATFORM, SONGS_PER_CLIP,
)
from utils.logger import log

# Supported music platforms
PLATFORMS = ["aimusicfactory", "suno", "udio", "musicgen"]

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
    elif platform == "musicgen":
        from modules.musicgen_generator import generate_music_batch
    else:
        from modules.music_generator import generate_music_batch
    return generate_music_batch


def _run_full_pipeline(gen_count: int = 1, platform: str = None, songs: int = None,
                       genre: str = "", music_style: str = "", thumbnail_style: str = "",
                       fusion: bool = False):
    """Full pipeline: generate music → merge → thumbnail → video → upload.

    Args:
        gen_count: Number of times to hit Generate (each gives 2 MP3s).
        platform: Music platform — "aimusicfactory", "suno", or "udio".
        songs: Total number of songs to generate (2, 4, 6, 8). Overrides gen_count.
        genre: Music genre (e.g. "Afro House", "Lo-Fi"). Falls back to config.
        music_style: Custom music style prompt. Falls back to config or default.
        thumbnail_style: Custom thumbnail prompt. Falls back to config or default.
        fusion: If True, use the fusion concept generator (Afro House × another genre).

    Note:
        On Suno we skip merging and split the 2 MP3s across the day — the
        first is uploaded now, the second is queued for a later scheduler slot
        via `flush-pending`.
    """
    from modules.audio_merger import merge_mp3s
    from modules.concept_generator import generate_concept, generate_fusion_concept
    from pipeline import process_single_track

    platform = platform or MUSIC_PLATFORM
    if songs:
        gen_count = max(1, songs // 2)  # Each generation = 2 songs

    generate_music_batch = _get_music_generator(platform)

    # Step 1: Generate concept first (for the music prompt)
    log.info("=" * 60)
    if fusion:
        log.info("STEP 1: Generating FUSION concept (Afro House × another genre)...")
        concept = generate_fusion_concept()
    else:
        log.info(f"STEP 1: Generating {genre or 'music'} concept...")
        concept = generate_concept(genre=genre, music_style=music_style,
                                   thumbnail_style=thumbnail_style)
    log.info(f"Track name: {concept.track_name}")

    # Step 2: Generate music
    log.info("=" * 60)
    log.info(f"STEP 2: Generating music on {platform} ({gen_count} generation(s) = {gen_count * 2} songs)...")
    mp3_files = generate_music_batch(concept, count=gen_count)
    log.info(f"Generated {len(mp3_files)} MP3 files")

    # Suno split-upload: each song uploaded separately, second deferred
    if platform == "suno" and len(mp3_files) >= 2:
        return _run_split_upload(mp3_files, base_concept=concept,
                                 genre=genre, music_style=music_style,
                                 thumbnail_style=thumbnail_style, fusion=fusion)

    # Step 3: Merge all MP3s into one track (non-Suno or single-track result)
    log.info("=" * 60)
    log.info("STEP 3: Merging MP3 files...")
    merged_path = merge_mp3s(mp3_files, output_name=concept.track_name)
    log.info(f"Merged file: {merged_path}")

    # Step 4-7: Process (duration, thumbnail, video, upload)
    result = process_single_track(merged_path, concept=concept)
    return result


def _run_split_upload(mp3_files, base_concept, genre="", music_style="",
                      thumbnail_style="", fusion=False):
    """Suno-only: upload each generated MP3 as its own YouTube video.

    First MP3 is uploaded immediately (full pipeline). Second MP3 is prepared
    (concept/thumbnail/video) and queued via pending_uploads — a later
    scheduler slot calls `flush-pending` to finish the upload.

    Each MP3 gets its own concept (fresh OpenAI call) and thumbnail (fresh
    DALL-E call) so the two uploads look like distinct videos on YouTube.
    """
    from modules.audio_merger import wav_from_mp3
    from modules.concept_generator import generate_concept, generate_fusion_concept
    from modules import pending_uploads
    from pipeline import prepare_track_assets, upload_prepared_track

    # Only the first pair gets the split — if Suno returned more than 2
    # (e.g. multiple batches), run the first pair split and merge-upload
    # the rest via the normal path for simplicity.
    first_two = mp3_files[:2]

    # Ensure WAV exists alongside each MP3 (ffmpeg — same convention as
    # audio_merger). Skips if already present.
    for mp3 in first_two:
        try:
            wav_from_mp3(mp3)
        except Exception as e:
            log.warning(f"Could not produce WAV for {mp3.name}: {e}")

    results = []
    for idx, mp3 in enumerate(first_two):
        log.info("#" * 60)
        log.info(f"SPLIT TRACK {idx + 1}/2: {mp3.name}")
        log.info("#" * 60)

        # Generate a fresh concept for each track so YouTube sees two
        # distinct videos (different title, description, thumbnail).
        if idx == 0:
            concept = base_concept
        else:
            try:
                if fusion:
                    concept = generate_fusion_concept()
                else:
                    concept = generate_concept(genre=genre, music_style=music_style,
                                               thumbnail_style=thumbnail_style)
                log.info(f"Fresh concept for track 2: {concept.track_name}")
            except Exception as e:
                log.warning(f"Could not generate fresh concept for track 2: {e} — reusing first")
                concept = base_concept

        try:
            prepared = prepare_track_assets(mp3, concept)
        except Exception as e:
            log.error(f"Prep failed for track {idx + 1}: {e}")
            results.append({"concept": concept.track_name, "errors": [f"prep: {e}"]})
            continue

        if idx == 0:
            # Upload first immediately
            result = upload_prepared_track(prepared)
            result["concept"] = concept.track_name
            results.append(result)
        else:
            # Queue second for later (flush-pending)
            try:
                pending_uploads.enqueue(
                    concept=concept,
                    video_path=prepared["video_path"],
                    thumbnail_path=prepared["thumbnail_path"],
                    mp3_path=prepared.get("mp3_path"),
                    wav_path=prepared.get("wav_path"),
                    cover_path=prepared.get("cover_path"),
                    duration_str=prepared.get("duration"),
                )
                results.append({
                    "concept": concept.track_name,
                    "queued": True,
                    "errors": [],
                })
                log.info(f"Track 2 ({concept.track_name}) queued for later upload")
            except Exception as e:
                log.error(f"Failed to queue track 2: {e}")
                results.append({"concept": concept.track_name, "errors": [f"queue: {e}"]})

    # Return the first track's result (keeps the existing error-counting
    # logic in cmd_run happy). The second is reported via log.
    primary = results[0] if results else {"errors": ["split: no tracks processed"], "concept": None}
    primary["split_results"] = results
    return primary


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


def cmd_bandcamp_login(args):
    """Open browser to log into Bandcamp and save session state.

    Uses the same browser setup as TuneCore/TikTok (Playwright-bundled
    Chromium with a stealth init script) — a real Chrome install is NOT
    required.
    """
    from playwright.sync_api import sync_playwright

    state_file = BANDCAMP_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    log.info("Opening browser for Bandcamp login...")
    log.info("Log in with your Bandcamp account, then come back here.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        # Stealth — same patches TuneCore uses
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()
        page.goto("https://bandcamp.com/login", wait_until="domcontentloaded", timeout=60_000)

        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Log into your Bandcamp artist account")
        log.info("  2. Wait until you see your dashboard / artist tools")
        log.info("  3. Come back here and press ENTER")
        log.info("=" * 60)

        input("\n>>> Press ENTER here after you've logged in... ")

        context.storage_state(path=str(state_file))
        log.info(f"Bandcamp session saved to: {state_file}")
        log.info("You can now run the pipeline and Bandcamp uploads will work!")

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


def cmd_suno_download(args):
    """Download the latest N tracks from Suno library, then run the pipeline.

    Skips music generation. Goes to https://suno.com/me, downloads the
    latest `--count` MP3s (default 2), merges → thumbnail → video → upload.
    Useful when you generated songs on Suno manually and just want the
    pipeline to finish them.
    """
    from modules.suno_generator import download_existing_tracks
    from modules.audio_merger import merge_mp3s
    from modules.concept_generator import generate_concept
    from pipeline import process_single_track

    track_name = args.name or ""
    count = args.count

    log.info("=" * 60)
    log.info(f"STEP 1: Downloading latest {count} track(s) from Suno library...")
    mp3_files = download_existing_tracks(track_name, max_cards=count)
    if not mp3_files:
        log.error("No MP3 files downloaded from Suno. Is the library empty or the session expired?")
        sys.exit(1)
    log.info(f"Downloaded {len(mp3_files)} MP3 files")

    log.info("=" * 60)
    log.info("STEP 2: Merging MP3 files...")
    merged_path = merge_mp3s(mp3_files, output_name=track_name or None)
    log.info(f"Merged file: {merged_path}")

    log.info("=" * 60)
    log.info("STEP 3-6: Concept → thumbnail → video → upload...")
    concept = generate_concept(track_name=track_name) if track_name else None
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
    fusion = getattr(args, "fusion", False)
    label = f"{count} clip(s) on {platform} ({songs} songs each, {gen_count} gen(s))"
    if fusion:
        label += " [FUSION]"
    log.info(f"Running full pipeline for {label}...")

    total_errors = 0
    for i in range(1, count + 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"CLIP {i}/{count}")
        log.info(f"{'#' * 60}")
        try:
            result = _run_full_pipeline(gen_count=gen_count, platform=platform, songs=songs, fusion=fusion)
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


def cmd_flush_pending(args):
    """Upload everything currently queued in output/pending_uploads/.

    Scheduler hook: call this from a late-day slot (e.g. 18:00) so the
    second track from each Suno split-generation gets uploaded a few hours
    after the first one.
    """
    from pipeline import flush_pending_uploads

    results = flush_pending_uploads()
    if not results:
        return
    failures = [r for r in results if r.get("errors")]
    log.info(f"Flushed {len(results)} pending upload(s), {len(failures)} error(s)")
    if failures:
        sys.exit(1)


def cmd_autostart(args):
    """Create Windows Task Scheduler tasks that run the pipeline at scheduled times.

    Creates one task per time slot (e.g. 13:00, 16:00, 19:00). Each task runs
    PowerShell directly — no CMD window, no VBS launcher needed.
    No administrator privileges required — uses the current user's context.
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
    task_prefix = "LUTH_Music_Pipeline"

    # (hour, minute, gen_count, extra_cli_args) — use cli_args="__FLUSH__"
    # for the late-day flush-pending slot (Suno split-upload second half).
    SCHEDULE_SLOTS = [
        (13, 0,  1, "--fusion"),   # 13:00 → FUSION: Afro House × another genre
        (16, 15, 2, ""),           # 16:15 → 2 gen = 4 MP3s
        (18, 0,  0, "__FLUSH__"),  # 18:00 → flush pending (Suno split 2nd half)
        (19, 0,  4, ""),           # 19:00 → 4 gen = 8 MP3s
    ]

    def _cleanup_all():
        """Remove all old launchers: Task Scheduler tasks, VBS, BAT from Startup."""
        # Remove old Task Scheduler tasks
        for old_task in ["MusicPipelineScheduler"]:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", old_task, "/F"],
                capture_output=True, text=True,
            )
        # Remove legacy MusicPipeline_* tasks (old naming convention)
        for i in range(1, 10):
            subprocess.run(
                ["schtasks", "/Delete", "/TN", f"MusicPipeline_{i}", "/F"],
                capture_output=True, text=True,
            )
        # Remove LUTH tasks (from previous autostart runs)
        for i in range(1, 10):
            subprocess.run(
                ["schtasks", "/Delete", "/TN", f"{task_prefix}_{i}", "/F"],
                capture_output=True, text=True,
            )
        # Remove old VBS/BAT files from Startup folder
        if startup_dir.is_dir():
            for f in startup_dir.iterdir():
                if f.suffix.lower() in ('.bat', '.vbs', '.cmd', '.lnk'):
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore") if f.suffix.lower() != '.lnk' else ""
                        if (f.suffix.lower() == '.lnk' and ("music" in f.name.lower() or "luth" in f.name.lower() or "pipeline" in f.name.lower())) or \
                           (project_dir in content or "music" in content.lower() or "pipeline" in content.lower() or "luth" in content.lower()):
                            f.unlink()
                            log.info(f"Removed old launcher from Startup: {f.name}")
                    except OSError:
                        pass
        # Remove old VBS from project dir
        for old_file in ["schedule_silent.vbs", "music_pipeline_schedule.ps1"]:
            old_path = Path(project_dir) / old_file
            if old_path.exists():
                old_path.unlink()
                log.info(f"Removed old file: {old_file}")

    if args.remove:
        _cleanup_all()
        log.info("All autostart tasks removed.")
        return

    _cleanup_all()

    # Build a PowerShell runner script for each slot
    venv_activate = Path(project_dir) / "venv" / "Scripts" / "Activate.ps1"
    venv2_activate = Path(project_dir) / ".venv" / "Scripts" / "Activate.ps1"
    venv_line = ""
    if venv_activate.exists():
        venv_line = r'& .\venv\Scripts\Activate.ps1'
    elif venv2_activate.exists():
        venv_line = r'& .\.venv\Scripts\Activate.ps1'

    ps_exe = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

    for i, (hour, minute, gen_count, extra_args) in enumerate(SCHEDULE_SLOTS, 1):
        task_name = f"{task_prefix}_{i}"
        if extra_args == "__FLUSH__":
            cli_args = "flush-pending"
        else:
            cli_args = f"run -g {gen_count}"
            if extra_args:
                cli_args += f" {extra_args}"

        # Create a small PS1 script for this slot
        ps1_name = f"music_pipeline_slot_{i}.ps1"
        ps1_path = Path(project_dir) / ps1_name
        if extra_args == "__FLUSH__":
            slot_label = "flush-pending (Suno split 2nd half)"
        elif extra_args == "--fusion":
            slot_label = f"{gen_count} generation(s) [FUSION]"
        else:
            slot_label = f"{gen_count} generation(s)"
        ps1_lines = [
            f'# LUTH Music Pipeline — Slot {i} ({hour}:{minute:02d})',
            f'# {slot_label}',
            '',
            '$ErrorActionPreference = "Continue"',
            f'Set-Location "{project_dir}"',
            '',
        ]
        if venv_line:
            ps1_lines.append(venv_line)
        ps1_lines.extend([
            '',
            f'& "{python}" main.py {cli_args}',
            '',
            'if ($LASTEXITCODE -ne 0) {',
            '    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"',
            f'    Add-Content -Path "output\\scheduler_errors.log" -Value "$timestamp — Slot {i} exited with code $LASTEXITCODE"',
            '}',
        ])
        ps1_path.write_text("\n".join(ps1_lines), encoding="utf-8")

        # Register Windows Task Scheduler task using PowerShell (no CMD)
        time_str = f"{hour:02d}:{minute:02d}"
        ps1_path_str = str(ps1_path).replace("'", "''")
        ps_argument = f"-ExecutionPolicy Bypass -NoProfile -NonInteractive -WindowStyle Hidden -File '{ps1_path_str}'"
        ps_command = (
            f"$action = New-ScheduledTaskAction "
            f"-Execute '{ps_exe}' "
            f"-Argument '{ps_argument}'; "
            f"$trigger = New-ScheduledTaskTrigger -Daily -At '{time_str}'; "
            f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; "
            f"Register-ScheduledTask -TaskName '{task_name}' -Action $action -Trigger $trigger -Settings $settings -Force"
        )

        result = subprocess.run(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps_command],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            if extra_args == "__FLUSH__":
                label = f"{time_str} → flush-pending"
            else:
                label = f"{time_str} → {gen_count} gen"
                if extra_args == "--fusion":
                    label += " [FUSION]"
            log.info(f"Task '{task_name}' created: {label}")
        else:
            log.error(f"Failed to create task '{task_name}': {result.stderr.strip()}")

    log.info("")
    log.info("Windows Task Scheduler tasks installed — NO CMD window, NO VBS needed.")
    log.info("Pipeline runs automatically at scheduled times, even if PowerShell is closed.")
    log.info("")
    log.info("To verify: run 'schtasks /Query /TN LUTH_Music_Pipeline_1' in PowerShell")
    log.info("To remove: python main.py autostart --remove")


def cmd_schedule(args):
    """Schedule 4 clips per day, uploaded to YouTube + TikTok automatically.

    Default schedule (Europe/Bucharest timezone):
      13:00 — 1 generate (FUSION: Afro House × another genre)
      16:00 — 2 generates (4 MP3s) → 1 clip
      19:00 — 4 generates (8 MP3s) → 1 clip

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

    # (hour, minute, gen_count, extra_kwargs) — gen_count × 2 MP3s merged into one clip
    # On Suno (MUSIC_PLATFORM=suno) the 13:00 slot generates 2 songs that are
    # split: the first uploads immediately, the second is queued and uploaded
    # at the 18:00 flush slot below.
    SCHEDULE_SLOTS = [
        (13, 0,  1, {"fusion": True}),   # 13:00 → FUSION: Afro House × Japanese/Greek/Latin Folk
        (16, 0,  2, {}),                  # 16:00 → 2 gen = 4 MP3s (ready ~16:15, before 18:00 peak)
        (19, 0,  4, {}),                  # 19:00 → 4 gen = 8 MP3s (ready ~19:15, before 21:00 peak)
    ]

    # Late-day flush slot: picks up any pending uploads queued earlier (e.g.
    # the second song from a Suno split at 13:00).
    FLUSH_HOUR, FLUSH_MINUTE = 18, 0

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
        for i, (hour, minute, gen_count, extra_kw) in enumerate(selected_slots):
            job_kwargs = {"gen_count": gen_count, **extra_kw}
            is_fusion = extra_kw.get("fusion", False)
            job_label = "FUSION" if is_fusion else f"{gen_count} gen"
            scheduler.add_job(
                _run_full_pipeline,
                CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE),
                kwargs=job_kwargs,
                id=f"music_pipeline_{i + 1}",
                name=f"Clip {i + 1} ({hour}:{minute:02d}, {job_label})",
                misfire_grace_time=MISFIRE_GRACE,
                coalesce=True,
            )
        schedule_desc = ", ".join(
            f"{h}:{m:02d} ({'FUSION' if kw.get('fusion') else f'{g} gen'})"
            for h, m, g, kw in selected_slots
        )
        log.info(f"Scheduled {len(selected_slots)} clips per day: {schedule_desc}")
        log.info(f"Timezone: {TIMEZONE} | Misfire grace: {MISFIRE_GRACE}s")

        # Flush pending uploads (Suno split-upload second half)
        from pipeline import flush_pending_uploads
        scheduler.add_job(
            flush_pending_uploads,
            CronTrigger(hour=FLUSH_HOUR, minute=FLUSH_MINUTE, timezone=TIMEZONE),
            id="flush_pending",
            name=f"Flush pending uploads ({FLUSH_HOUR}:{FLUSH_MINUTE:02d})",
            misfire_grace_time=MISFIRE_GRACE,
            coalesce=True,
        )
        log.info(f"Flush slot: {FLUSH_HOUR}:{FLUSH_MINUTE:02d} (uploads any queued tracks)")

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

    # bandcamp-login - save Bandcamp session state
    bandcamp_login_parser = subparsers.add_parser(
        "bandcamp-login",
        help="Log into Bandcamp and save session for automated uploads",
    )
    bandcamp_login_parser.set_defaults(func=cmd_bandcamp_login)

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

    # suno-download - grab the latest N tracks from Suno library and process them
    suno_dl_parser = subparsers.add_parser(
        "suno-download",
        help="Download the latest N tracks from Suno → merge → thumbnail → video → YouTube",
    )
    suno_dl_parser.add_argument(
        "--count", type=int, default=2,
        help="Number of latest tracks to download from Suno library (default: 2)",
    )
    suno_dl_parser.add_argument(
        "--name", type=str, default=None,
        help="Optional track name for the merged output (default: AI picks one)",
    )
    suno_dl_parser.set_defaults(func=cmd_suno_download)

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
        "--only", choices=["youtube", "tiktok", "tunecore", "soundcloud", "bandcamp"],
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
    run_parser.add_argument(
        "--fusion", action="store_true", default=False,
        help="Use fusion concept generator (Afro House × another genre)",
    )
    run_parser.set_defaults(func=cmd_run)

    # flush-pending - upload tracks queued by split-upload mode
    flush_parser = subparsers.add_parser(
        "flush-pending",
        help="Upload tracks queued in output/pending_uploads/ (Suno split-upload second half)",
    )
    flush_parser.set_defaults(func=cmd_flush_pending)

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
