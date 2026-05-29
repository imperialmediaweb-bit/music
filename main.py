#!/usr/bin/env python3
"""Afro House Music Pipeline — Full automation: generate, merge, thumbnail, video, upload."""

import argparse
import os
import random
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
    BANDCAMP_STATE_FILE, MUSIC_PLATFORM, SONGS_PER_CLIP, SKIP_ARCHIVE,
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


def _run_full_pipeline(gen_count: int = 0, platform: str = None, songs: int = None,
                       genre: str = "", music_style: str = "", thumbnail_style: str = "",
                       fusion: bool = False, profile_name: str = "",
                       target_minutes: int = 0):
    """Full pipeline: generate music → merge → thumbnail → video → upload.

    Args:
        gen_count: Number of times to hit Generate (each gives 2 MP3s).
        platform: Music platform — "aimusicfactory", "suno", or "udio".
        songs: Total number of songs to generate (2, 4, 6, 8). Overrides gen_count.
        genre: Music genre (e.g. "Afro House", "Lo-Fi"). Falls back to config.
        music_style: Custom music style prompt. Falls back to config or default.
        thumbnail_style: Custom thumbnail prompt. Falls back to config or default.
        fusion: If True, use the fusion concept generator (Afro House × another genre).
        profile_name: Playlist profile ("main", "gym", "driving", "focus",
            "meditation"). If empty, uses today's profile from WEEKLY_PLAN.
        target_minutes: Target duration in minutes. If set, overrides profile's
            fresh_count/archive_count to hit this duration.
    """
    from modules.audio_merger import merge_mp3s, merge_mp3s_crossfade, trim_quiet_intro
    from modules.archive_manager import archive_mp3s, pick_from_archive, archive_size
    from modules.concept_generator import generate_concept, generate_fusion_concept
    from modules.profiles import PLAYLIST_PROFILES, get_todays_profile, get_random_thumbnail_style
    from pipeline import process_single_track

    platform = platform or MUSIC_PLATFORM

    # Load playlist profile (explicit or today's from weekly plan)
    if profile_name and profile_name in PLAYLIST_PROFILES:
        profile = PLAYLIST_PROFILES[profile_name]
    else:
        profile_name, profile = get_todays_profile()
    log.info(f"Playlist profile: {profile_name} ({profile['label']})")

    # Use profile's fresh_count as default (gen_count=0 means "use profile")
    # Each generation = 2 MP3s, each MP3 ≈ 2 min
    if songs:
        gen_count = max(1, songs // 2)
    elif gen_count <= 0:
        if target_minutes > 0:
            gen_count = max(2, target_minutes // 8)
        else:
            gen_count = profile.get("fresh_count", 2)

    # Profile feeds into existing generate_concept params (only if not overridden)
    if not music_style and profile.get("suno_prompt_addition"):
        music_style = profile["suno_prompt_addition"]
    if not thumbnail_style and profile.get("thumbnail_style_variants"):
        thumbnail_style = get_random_thumbnail_style(profile)
    extra_playlists = profile.get("youtube_playlists", [])[1:]  # skip first (= genre playlist)
    crossfade_sec = profile.get("crossfade_sec", 0)

    generate_music_batch = _get_music_generator(platform)

    # Step 1: Generate concept first (for the music prompt)
    log.info("=" * 60)
    if fusion:
        log.info("STEP 1: Generating FUSION concept (Afro House × another genre)...")
        concept = generate_fusion_concept()
    else:
        log.info(f"STEP 1: Generating {genre or 'music'} concept ({profile_name} profile)...")
        concept = generate_concept(genre=genre, music_style=music_style,
                                   thumbnail_style=thumbnail_style)
    log.info(f"Track name: {concept.track_name}")

    # Step 2: Generate music
    log.info("=" * 60)
    log.info(f"STEP 2: Generating music on {platform} ({gen_count} generation(s) = {gen_count * 2} songs)...")
    mp3_files = generate_music_batch(concept, count=gen_count)
    log.info(f"Generated {len(mp3_files)} MP3 files")

    # Trim quiet intros from individual MP3s before merging
    mp3_files = [trim_quiet_intro(f) for f in mp3_files]

    # Save fresh MP3s to archive for future hybrid use
    archive_mp3s(mp3_files, profile_name=profile_name,
                 track_name=concept.track_name,
                 tags=profile.get("extra_tags", []))

    # Hybrid mode: add archived MP3s if pool is large enough
    archive_mp3s_list = []
    if SKIP_ARCHIVE:
        if profile.get("hybrid"):
            log.info("Hybrid mode SKIPPED — using fresh tracks only (SKIP_ARCHIVE=true)")
    elif profile.get("hybrid") and archive_size() >= profile.get("archive_min_pool", 12):
        if target_minutes > 0:
            fresh_minutes = len(mp3_files) * 2
            want = max(0, (target_minutes - fresh_minutes) // 2)
        else:
            want = profile.get("archive_count", 2)
        if want > 0:
            archive_mp3s_list = pick_from_archive(want, exclude_files=mp3_files)
        if archive_mp3s_list:
            log.info(f"Hybrid mode: {len(mp3_files)} fresh + {len(archive_mp3s_list)} from archive")
            mp3_files = mp3_files + archive_mp3s_list
            random.shuffle(mp3_files)
    else:
        if profile.get("hybrid"):
            pool = archive_size()
            needed = profile.get("archive_min_pool", 12)
            log.info(f"Hybrid mode waiting — pool {pool}/{needed} MP3s (need more generations)")

    # Step 3: Merge all MP3s into one track (with crossfade if profile uses it)
    log.info("=" * 60)
    if crossfade_sec > 0 and len(mp3_files) > 1:
        log.info(f"STEP 3: Merging {len(mp3_files)} MP3 files with {crossfade_sec}s crossfade...")
        merged_path = merge_mp3s_crossfade(mp3_files, output_name=concept.track_name,
                                            crossfade_sec=crossfade_sec)
    else:
        log.info(f"STEP 3: Merging {len(mp3_files)} MP3 files...")
        merged_path = merge_mp3s(mp3_files, output_name=concept.track_name)
    log.info(f"Merged file: {merged_path}")

    # Step 4-7: Process (duration, thumbnail, video, upload)
    result = process_single_track(merged_path, concept=concept,
                                  extra_playlists=extra_playlists,
                                  profile_data=profile,
                                  segment_files=mp3_files)
    return result


def _run_generate_only(gen_count: int = 2, profile_name: str = ""):
    """Generate music + thumbnail + video and queue for later publishing.

    This is the "overnight" step: runs at 02:00 daily, creates all assets,
    saves them to the pending-uploads queue. The publish step
    (_run_publish_only) uploads them at the right time during the week.
    """
    from modules.audio_merger import merge_mp3s, merge_mp3s_crossfade, trim_quiet_intro
    from modules.concept_generator import generate_concept
    from modules.profiles import PLAYLIST_PROFILES, get_todays_profile, get_random_thumbnail_style
    from modules import pending_uploads
    from pipeline import prepare_track_assets

    platform = MUSIC_PLATFORM

    if profile_name and profile_name in PLAYLIST_PROFILES:
        profile = PLAYLIST_PROFILES[profile_name]
    else:
        profile_name, profile = get_todays_profile()
    log.info(f"[GENERATE] Profile: {profile_name} ({profile['label']})")

    music_style = profile.get("suno_prompt_addition", "")
    thumbnail_style = get_random_thumbnail_style(profile)
    extra_playlists = profile.get("youtube_playlists", [])[1:]
    crossfade_sec = profile.get("crossfade_sec", 0)

    generate_music_batch = _get_music_generator(platform)

    log.info("=" * 60)
    log.info(f"[GENERATE] STEP 1: Generating concept ({profile_name})...")
    concept = generate_concept(music_style=music_style, thumbnail_style=thumbnail_style)
    log.info(f"Track name: {concept.track_name}")

    log.info("=" * 60)
    log.info(f"[GENERATE] STEP 2: Generating music on {platform}...")
    mp3_files = generate_music_batch(concept, count=gen_count)
    log.info(f"Generated {len(mp3_files)} MP3 files")

    mp3_files = [trim_quiet_intro(f) for f in mp3_files]

    log.info("=" * 60)
    if crossfade_sec > 0 and len(mp3_files) > 1:
        log.info(f"[GENERATE] STEP 3: Merging with {crossfade_sec}s crossfade...")
        merged_path = merge_mp3s_crossfade(mp3_files, output_name=concept.track_name,
                                            crossfade_sec=crossfade_sec)
    else:
        log.info("[GENERATE] STEP 3: Merging MP3 files...")
        merged_path = merge_mp3s(mp3_files, output_name=concept.track_name)

    log.info("=" * 60)
    log.info("[GENERATE] STEP 4: Creating thumbnail + video...")
    prepared = prepare_track_assets(merged_path, concept)

    log.info("=" * 60)
    log.info("[GENERATE] STEP 5: Queueing for publish...")
    sidecar = pending_uploads.enqueue(
        concept=concept,
        video_path=prepared["video_path"],
        thumbnail_path=prepared["thumbnail_path"],
        mp3_path=prepared.get("mp3_path"),
        wav_path=prepared.get("wav_path"),
        cover_path=prepared.get("cover_path"),
        duration_str=prepared.get("duration"),
        extra_playlists=extra_playlists,
    )
    log.info(f"[GENERATE] Queued: {sidecar.name} — ready for publish slot")


def _run_publish_only():
    """Upload all queued tracks to YouTube/TikTok/TuneCore.

    This is the "publish" step: runs 4x/week at optimal hours. Picks up
    everything queued by _run_generate_only and uploads it.
    """
    from pipeline import flush_pending_uploads
    log.info("[PUBLISH] Flushing pending uploads...")
    flush_pending_uploads()
    log.info("[PUBLISH] Done")


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


def cmd_bandcamp_latest(args):
    """Find the most recent WAV + cover in output/ and upload to Bandcamp.

    Usage: python main.py bandcamp-latest
    """
    from config import OUTPUT_DIR
    from modules.bandcamp_uploader import upload_to_bandcamp
    from modules.concept_generator import MusicConcept

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

    stem = cover_path.stem
    for tag in ("_thumbnail", "_cover"):
        stem = stem.replace(tag, "")
    track_name = stem.replace("_", " ")
    log.info(f"Track name: {track_name}")

    wav_path = None
    for name_variant in [stem, track_name.replace(" ", "_")]:
        candidate = OUTPUT_DIR / f"{name_variant}.wav"
        if candidate.exists():
            wav_path = candidate
            break

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

    result = upload_to_bandcamp(wav_path, concept, cover_path)
    if result:
        log.info(f"Done! Bandcamp result: {result}")
    else:
        log.error("Bandcamp upload failed — check logs and screenshots in output/")
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
    """Open YOUR real Chrome to log into Bandcamp, then extract cookies.

    Bandcamp's reCAPTCHA rejects any Playwright-launched browser (even real
    Chrome via channel='chrome'). So we launch Chrome directly via
    subprocess — with a dedicated profile dir and a debug port — then
    connect Playwright via CDP only to grab cookies AFTER the user has
    logged in.
    """
    import subprocess as sp
    import platform as plat
    import shutil
    from playwright.sync_api import sync_playwright

    state_file = BANDCAMP_STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # ── Find the real Chrome binary ──
    chrome = _find_chrome_binary()
    if not chrome:
        log.error("Google Chrome not found. Install Chrome or set CHROME_PATH env var.")
        sys.exit(1)
    log.info(f"Chrome: {chrome}")

    # ── Dedicated profile dir (so we don't lock the user's main Chrome) ──
    profile_dir = str(BANDCAMP_STATE_FILE.parent / "bandcamp_chrome_profile")
    debug_port = "9224"

    log.info("Launching Chrome for Bandcamp login...")
    log.info("  → reCAPTCHA requires a native Chrome (not Playwright)")
    log.info("  → Log in, then come back here and press ENTER")

    chrome_proc = sp.Popen([
        chrome,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://bandcamp.com/login",
    ])

    log.info("=" * 60)
    log.info("Chrome window is open. Please:")
    log.info("  1. Log into your Bandcamp artist account")
    log.info("  2. Wait until you see your dashboard / feed")
    log.info("  3. Come back here and press ENTER")
    log.info("=" * 60)

    input("\n>>> Press ENTER here after you've logged in... ")

    # ── Connect via CDP and extract cookies ──
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
            context = browser.contexts[0]
            context.storage_state(path=str(state_file))
            log.info(f"Bandcamp session saved to: {state_file}")
            log.info("You can now run the pipeline and Bandcamp uploads will work!")
            browser.close()
    except Exception as e:
        log.error(f"Could not connect to Chrome debug port: {e}")
        log.info("Make sure Chrome is still open when you press ENTER.")
    finally:
        # Close the Chrome process
        try:
            chrome_proc.terminate()
        except Exception:
            pass


def _find_chrome_binary() -> str | None:
    """Locate the Google Chrome executable on this system."""
    import platform as plat
    import shutil

    # 1. Explicit env var
    env = os.environ.get("CHROME_PATH")
    if env and os.path.isfile(env):
        return env

    system = plat.system()
    if system == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        # Fallback: search PATH
        found = shutil.which("chrome") or shutil.which("google-chrome")
        return found
    elif system == "Darwin":
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        return mac if os.path.isfile(mac) else shutil.which("google-chrome")
    else:
        return shutil.which("google-chrome") or shutil.which("chromium-browser") or shutil.which("chromium")


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
    playlist_profile = getattr(args, "playlist", "") or ""
    target_minutes = getattr(args, "target_minutes", 0) or 0
    label = f"{count} clip(s) on {platform} ({songs} songs each, {gen_count} gen(s))"
    if target_minutes:
        label += f" [~{target_minutes}min]"
    if playlist_profile:
        label += f" [{playlist_profile}]"
    if fusion:
        label += " [FUSION]"
    log.info(f"Running full pipeline for {label}...")

    total_errors = 0
    for i in range(1, count + 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"CLIP {i}/{count}")
        log.info(f"{'#' * 60}")
        try:
            result = _run_full_pipeline(gen_count=gen_count, platform=platform, songs=songs,
                                        fusion=fusion, profile_name=playlist_profile,
                                        target_minutes=target_minutes)
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


def cmd_seed_archive(args):
    """Import existing MP3s from output/ into the archive pool.

    Scans output/ for individual Suno MP3s (files ending in _1.mp3, _2.mp3, etc)
    and copies them into the archive pool. After this, hybrid mode will
    automatically use these archived songs to create longer tracks.
    """
    from modules.archive_manager import seed_from_output, archive_size
    count = seed_from_output()
    log.info(f"Archive pool now has {archive_size()} MP3s")
    if count == 0:
        log.info("No new MP3s to import (all already in archive)")


def cmd_update_seo(args):
    """Bulk update SEO on all existing YouTube videos.

    Goes through all uploaded videos and updates tags, description keywords,
    and localizations with current year and trending terms.
    """
    from modules.youtube_uploader import _get_authenticated_service, _set_localizations, LOCALIZATION_TEMPLATES
    from modules.concept_generator import MusicConcept

    youtube = _get_authenticated_service()

    channels = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    all_videos = []
    next_page = None
    while True:
        playlist_items = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_playlist,
            maxResults=50, pageToken=next_page,
        ).execute()
        all_videos.extend(playlist_items.get("items", []))
        next_page = playlist_items.get("nextPageToken")
        if not next_page:
            break

    log.info(f"Found {len(all_videos)} videos to update")

    seo_block = (
        "\n\nafro house mix 2026, best afro house 2026, "
        "new afro house music, deep house mix 2026, "
        "tribal house 2026, african music 2026, "
        "electronic music 2026, house music mix, "
        "workout music 2026, gym music, driving music, "
        "study music, focus music, meditation music, "
        "new music 2026, trending music, viral music 2026"
    )

    updated = 0
    for item in all_videos:
        video_id = item["snippet"]["resourceId"]["videoId"]
        try:
            video = youtube.videos().list(
                part="snippet,localizations", id=video_id
            ).execute()
            if not video.get("items"):
                continue
            v = video["items"][0]
            snippet = v["snippet"]
            desc = snippet.get("description", "")
            title = snippet.get("title", "")

            if "2026" in desc and "trending music" in desc:
                continue

            if seo_block.strip() not in desc:
                new_desc = (desc.rstrip() + seo_block)[:5000]
                snippet["description"] = new_desc

            youtube.videos().update(
                part="snippet",
                body={"id": video_id, "snippet": snippet},
            ).execute()

            if not v.get("localizations"):
                _set_localizations(youtube, video_id, title, new_desc,
                                   type("C", (), {"genre": "Afro House"})())

            updated += 1
            log.info(f"Updated {updated}/{len(all_videos)}: {title[:50]}")
        except Exception as e:
            log.warning(f"Failed to update {video_id}: {e}")

    log.info(f"SEO update complete: {updated}/{len(all_videos)} videos updated")


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

    # 2x/day: short at 14:00 + long at 19:00 (profile/duration auto from weekly plan)
    SCHEDULE_SLOTS = [
        (14, 0, 0, ""),   # 14:00 → short track (~20 min)
        (19, 0, 0, ""),   # 19:00 → long track (~40 min)
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
            cli_args = f"run"
            if gen_count > 0:
                cli_args += f" -g {gen_count}"
            if extra_args:
                cli_args += f" {extra_args}"

        # Create a small PS1 script for this slot
        ps1_name = f"music_pipeline_slot_{i}.ps1"
        ps1_path = Path(project_dir) / ps1_name
        if extra_args == "__FLUSH__":
            slot_label = "flush-pending"
        else:
            slot_label = extra_args or "auto (profile-driven)"
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
            f'$logTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"',
            f'$logFile = "output\\scheduler_slot_{i}_$logTimestamp.log"',
            f'New-Item -ItemType Directory -Force -Path "output" | Out-Null',
            f'"=== Slot {i} started $(Get-Date) ===" | Out-File -FilePath $logFile -Encoding UTF8',
            f'& "{python}" main.py {cli_args} *>> $logFile',
            f'"=== Slot {i} exited with code $LASTEXITCODE at $(Get-Date) ===" | Out-File -FilePath $logFile -Append -Encoding UTF8',
            '',
            'if ($LASTEXITCODE -ne 0) {',
            '    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"',
            f'    Add-Content -Path "output\\scheduler_errors.log" -Value "$timestamp - Slot {i} exited with code $LASTEXITCODE (see $logFile)"',
            '}',
        ])
        ps1_path.write_text("\n".join(ps1_lines), encoding="utf-8")

        # Register Windows Task Scheduler task using PowerShell (no CMD)
        time_str = f"{hour:02d}:{minute:02d}"
        # Use double quotes around the PS1 path inside the (single-quoted)
        # PS argument string. Nesting single quotes broke parsing and Windows
        # ended up running the task with no working directory → 0x8007010B
        # (ERROR_DIRECTORY) on launch.
        ps1_path_str = str(ps1_path)
        project_dir_ps = project_dir.replace("'", "''")
        ps_argument = (
            f'-ExecutionPolicy Bypass -NoProfile -NonInteractive '
            f'-WindowStyle Hidden -File "{ps1_path_str}"'
        )
        # Build a StartBoundary anchored to today (or tomorrow if the time
        # already passed) so the first run is the upcoming HH:MM, not skipped
        # to next day by PowerShell's default trigger handling.
        ps_command = (
            f"$action = New-ScheduledTaskAction "
            f"-Execute '{ps_exe}' "
            f"-Argument '{ps_argument}' "
            f"-WorkingDirectory '{project_dir_ps}'; "
            f"$now = Get-Date; "
            f"$start = Get-Date -Hour {hour} -Minute {minute} -Second 0 -Millisecond 0; "
            f"if ($start -lt $now) {{ $start = $start.AddDays(1) }}; "
            f"$trigger = New-ScheduledTaskTrigger -Daily -At $start; "
            f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun; "
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
                label = f"{time_str} → {slot_label}"
            log.info(f"Task '{task_name}' created: {label}")
        else:
            log.error(f"Failed to create task '{task_name}': {result.stderr.strip()}")

    log.info("")
    log.info("Windows Task Scheduler tasks installed — NO CMD window, NO VBS needed.")
    log.info("Pipeline runs automatically at scheduled times, even if PowerShell is closed.")
    log.info("Tasks WAKE the PC from sleep (-WakeToRun) and run missed slots on next wake (-StartWhenAvailable).")
    log.info("")
    log.info("⚠ For wake-from-sleep to work, Windows wake timers must be enabled:")
    log.info("   Settings → System → Power & battery → Power mode → Best performance")
    log.info("   OR: powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1")
    log.info("       powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1   (on battery)")
    log.info("")
    log.info("To verify: run 'schtasks /Query /TN LUTH_Music_Pipeline_1 /V /FO LIST' in PowerShell")
    log.info("To remove: python main.py autostart --remove")


def cmd_schedule(args):
    """Schedule 2 clips per day: 14:00 (short ~20min) + 19:00 (long ~40min).

    Default schedule (Europe/Bucharest timezone):
      Every day 14:00 — short track (~20 min), alternating profiles
      Every day 19:00 — long track (~40 min), alternating profiles

    Both use aimusicfactory + archive hybrid mode.
    Each video gets 1 Short + 1 pinned comment.

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

    # 2x/day: short at 14:00 (~20 min) + long at 19:00 (~40 min)
    # (day_of_week, hour, minute, gen_count, profile_name, target_minutes)
    WEEKLY_SCHEDULE = [
        ("mon", 14, 0, 0, "main",       20),
        ("mon", 19, 0, 0, "gym",        40),
        ("tue", 14, 0, 0, "focus",      20),
        ("tue", 19, 0, 0, "main",       40),
        ("wed", 14, 0, 0, "main",       20),
        ("wed", 19, 0, 0, "driving",    40),
        ("thu", 14, 0, 0, "gym",        20),
        ("thu", 19, 0, 0, "focus",      40),
        ("fri", 14, 0, 0, "main",       20),
        ("fri", 19, 0, 0, "main",       40),
        ("sat", 14, 0, 0, "driving",    20),
        ("sat", 19, 0, 0, "meditation", 40),
        ("sun", 14, 0, 0, "meditation", 20),
        ("sun", 19, 0, 0, "main",       40),
    ]

    # 1 hour grace — if PC wakes from sleep within 1h, the job still fires
    MISFIRE_GRACE = 3600

    if args.cron:
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
        clips_per_week = args.clips or len(WEEKLY_SCHEDULE)
        selected_slots = WEEKLY_SCHEDULE[:clips_per_week]
        for i, (dow, hour, minute, gen_count, profile, tgt_min) in enumerate(selected_slots):
            scheduler.add_job(
                _run_full_pipeline,
                CronTrigger(day_of_week=dow, hour=hour, minute=minute,
                            timezone=TIMEZONE),
                kwargs={"gen_count": gen_count, "profile_name": profile,
                         "target_minutes": tgt_min},
                id=f"music_pipeline_{i + 1}",
                name=f"{dow.upper()} {hour}:{minute:02d} — {profile} (~{tgt_min}min)",
                misfire_grace_time=MISFIRE_GRACE,
                coalesce=True,
            )
        schedule_desc = ", ".join(
            f"{dow.upper()} {h}:{m:02d} ({prof} ~{t}min)"
            for dow, h, m, g, prof, t in selected_slots
        )
        log.info(f"Scheduled {len(selected_slots)} slots/week: {schedule_desc}")
        log.info(f"Timezone: {TIMEZONE} | Misfire grace: {MISFIRE_GRACE}s")

        # Auto-reply to comments 2x/day (10:00 and 20:00)
        def _auto_reply_job():
            from modules.youtube_uploader import reply_to_new_comments
            reply_to_new_comments(max_videos=5, max_replies_per_video=3)

        scheduler.add_job(
            _auto_reply_job,
            CronTrigger(hour="10,20", minute=0, timezone=TIMEZONE),
            id="auto_reply_comments",
            name="Auto-reply to YouTube comments (10:00 & 20:00)",
            misfire_grace_time=MISFIRE_GRACE,
            coalesce=True,
        )
        log.info("Scheduled auto-reply to comments at 10:00 & 20:00 daily")

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

    # bandcamp-latest - auto-find latest WAV + cover and upload to Bandcamp
    subparsers.add_parser(
        "bandcamp-latest",
        help="Find latest WAV + cover art in output/ and upload to Bandcamp",
    ).set_defaults(func=cmd_bandcamp_latest)

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

    # seed-archive - import existing MP3s into archive pool
    subparsers.add_parser(
        "seed-archive",
        help="Import existing MP3s from output/ into archive pool for hybrid mode",
    ).set_defaults(func=cmd_seed_archive)

    # update-seo - bulk update SEO on all existing YouTube videos
    subparsers.add_parser(
        "update-seo",
        help="Bulk update SEO keywords, description, and localizations on all YouTube videos",
    ).set_defaults(func=cmd_update_seo)

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
        "-g", "--gens", type=int, default=0,
        help="Generations per clip — each generation = 2 MP3s (default: from profile fresh_count)",
    )
    run_parser.add_argument(
        "--fusion", action="store_true", default=False,
        help="Use fusion concept generator (Afro House × another genre)",
    )
    run_parser.add_argument(
        "--playlist", choices=["main", "gym", "driving", "focus", "meditation"], default="",
        help="Playlist profile to use (default: auto from weekly plan)",
    )
    run_parser.add_argument(
        "--target-minutes", type=int, default=0,
        help="Target track duration in minutes (overrides profile defaults)",
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
