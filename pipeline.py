import json
import subprocess
from pathlib import Path

from utils.logger import log
from utils.auto_setup import ensure_path
from modules.concept_generator import generate_concept
from modules.thumbnail_generator import generate_thumbnail, generate_cover_art, generate_thumbnail_and_cover
from modules.video_creator import create_video
from modules.youtube_uploader import upload_to_youtube
from modules.tiktok_uploader import upload_to_tiktok
from modules.tunecore_uploader import upload_to_tunecore
from modules.soundcloud_uploader import upload_to_soundcloud
from config import SKIP_TUNECORE, SKIP_SOUNDCLOUD

# Default artist name (used for cover art overlay and TuneCore metadata)
DEFAULT_ARTIST = "GrooveGenix"


def reupload_track(track_name: str, only: str | None = None) -> dict:
    """Re-upload an existing track to YouTube and TikTok (skip generation/video steps).

    Looks for existing files in OUTPUT_DIR:
      - {track_name}_video.mp4
      - {track_name}_thumbnail.jpg (or .png for older tracks)
      - {track_name}.mp3  (for duration detection)

    Regenerates concept metadata (title, description, tags) via OpenAI,
    then uploads to both platforms.
    """
    ensure_path()
    from config import OUTPUT_DIR
    from modules.concept_generator import generate_concept

    result = {
        "concept": track_name,
        "duration": None,
        "youtube_url": None,
        "tiktok_url": None,
        "tunecore_url": None,
        "soundcloud_url": None,
        "errors": [],
    }

    # Locate existing files — check multiple naming conventions
    video = None
    for suffix in ["_video.mp4", "_tiktok.mp4", ".mp4"]:
        candidate = OUTPUT_DIR / f"{track_name}{suffix}"
        if candidate.exists():
            video = candidate
            break
    # Check both .jpg (new) and .png (old) thumbnail formats
    thumbnail = OUTPUT_DIR / f"{track_name}_thumbnail.jpg"
    if not thumbnail.exists():
        thumbnail = OUTPUT_DIR / f"{track_name}_thumbnail.png"
    mp3_file = OUTPUT_DIR / f"{track_name}.mp3"

    if not thumbnail.exists():
        log.warning(f"Thumbnail not found: {thumbnail} — continuing without it")

    if not video and only != "tunecore":
        log.error(f"Video not found in output/ (tried _video.mp4, _tiktok.mp4, .mp4)")
        result["errors"].append(f"missing: {track_name} video in {OUTPUT_DIR}")
        return result

    if video:
        log.info(f"Found video: {video}")

    # Detect duration from MP3 (if available)
    duration_sec = 0
    if mp3_file.exists():
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(mp3_file)],
                capture_output=True, text=True,
            )
            duration_sec = float(json.loads(probe.stdout)["format"]["duration"])
            result["duration"] = _format_duration(duration_sec)
            log.info(f"Duration: {result['duration']}")
        except Exception:
            log.warning("Could not detect duration — continuing without it")

    # Generate fresh concept metadata
    log.info("=" * 60)
    log.info(f"Generating concept metadata for '{track_name}'...")
    concept = generate_concept(track_name=track_name)

    # Inject duration into title (same logic as process_single_track)
    if duration_sec:
        duration_mins = int(duration_sec) // 60
        if "\U0001f525" in concept.youtube_title:
            concept.youtube_title = concept.youtube_title.replace(
                "\U0001f525", f"\U0001f525 {duration_mins} Minutes of", 1
            )
        concept.youtube_title = concept.youtube_title[:100]
        concept.youtube_description = concept.youtube_description.replace(
            "{duration}", str(duration_mins)
        )
        concept.youtube_description += f"\n\nDuration: {result['duration']}"

    log.info(f"YouTube title: {concept.youtube_title}")

    # Upload to YouTube
    if only in (None, "youtube"):
        try:
            log.info("=" * 60)
            log.info("Uploading to YouTube...")
            youtube_url = upload_to_youtube(video, thumbnail, concept)
            result["youtube_url"] = youtube_url
            if youtube_url:
                log.info(f"YouTube URL: {youtube_url}")
            else:
                log.error("YouTube upload returned None — check client_secrets.json and OAuth token")
                result["errors"].append("youtube: upload returned None (check client_secrets.json / OAuth)")
        except Exception as e:
            log.error(f"YouTube upload failed: {e}")
            result["errors"].append(f"youtube: {e}")
    else:
        log.info(f"Skipping YouTube (--only {only})")

    # Upload to TikTok
    if only in (None, "tiktok"):
        try:
            log.info("=" * 60)
            log.info("Uploading to TikTok...")
            tiktok_url = upload_to_tiktok(video, concept)
            result["tiktok_url"] = tiktok_url
            if tiktok_url:
                log.info(f"TikTok: {tiktok_url}")
            else:
                log.error("TikTok upload returned None — check cookies/login above")
                result["errors"].append("tiktok: upload returned None (cookies expired or login redirect)")
        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            result["errors"].append(f"tiktok: {e}")
    else:
        log.info(f"Skipping TikTok (--only {only})")

    # Upload to TuneCore (always runs with youtube/tiktok too)
    if only in (None, "tunecore", "youtube", "tiktok"):
        # Files may use underscores instead of spaces (audio_merger convention)
        name_variants = [track_name, track_name.replace(" ", "_")]
        wav_file = None
        for name in name_variants:
            candidate = OUTPUT_DIR / f"{name}.wav"
            if candidate.exists():
                wav_file = candidate
                break
        # Fallback: pick the most recently modified WAV in output/
        if not wav_file:
            all_wavs = sorted(OUTPUT_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
            all_wavs += sorted(OUTPUT_DIR.glob("*.WAV"), key=lambda f: f.stat().st_mtime, reverse=True)
            if all_wavs:
                wav_file = all_wavs[0]
                log.info(f"WAV not found by name — using latest: {wav_file}")

        # Look for existing cover art
        cover_file = None
        for name in name_variants:
            for suffix in ["_cover.jpg", "_cover.png"]:
                candidate = OUTPUT_DIR / f"{name}{suffix}"
                if candidate.exists():
                    cover_file = candidate
                    break
            if cover_file:
                break

        if not wav_file:
            log.warning(f"WAV file not found in {OUTPUT_DIR} — skipping TuneCore")
            result["errors"].append(f"tunecore: WAV not found in {OUTPUT_DIR}")
        elif not cover_file:
            # Generate cover art if missing
            try:
                log.info("=" * 60)
                log.info("Generating 1600x1600 cover art for TuneCore...")
                cover_file = generate_cover_art(
                    concept.thumbnail_prompt, concept.track_name, DEFAULT_ARTIST
                )
                log.info(f"Cover art: {cover_file}")
            except Exception as e:
                log.error(f"Cover art generation failed: {e}")
                result["errors"].append(f"cover_art: {e}")

        if wav_file and cover_file:
            try:
                log.info("=" * 60)
                log.info("Uploading to TuneCore...")
                tunecore_url = upload_to_tunecore(wav_file, cover_file, concept)
                result["tunecore_url"] = tunecore_url
                if tunecore_url:
                    log.info(f"TuneCore: {tunecore_url}")
                else:
                    log.error("TuneCore upload returned None — run: python main.py tunecore-login")
                    result["errors"].append("tunecore: upload returned None (session expired)")
            except Exception as e:
                log.error(f"TuneCore upload failed: {e}")
                result["errors"].append(f"tunecore: {e}")
    else:
        log.info(f"Skipping TuneCore (--only {only})")

    # Upload to SoundCloud
    if only in (None, "soundcloud"):
        # Reuse the same WAV + cover art files
        name_variants = [track_name, track_name.replace(" ", "_")]
        sc_wav = None
        for name in name_variants:
            candidate = OUTPUT_DIR / f"{name}.wav"
            if candidate.exists():
                sc_wav = candidate
                break
        sc_cover = None
        for name in name_variants:
            for suffix in ["_cover.jpg", "_cover.png"]:
                candidate = OUTPUT_DIR / f"{name}{suffix}"
                if candidate.exists():
                    sc_cover = candidate
                    break
            if sc_cover:
                break

        if not sc_wav:
            # Fall back to MP3 if no WAV
            sc_wav = mp3_file if mp3_file.exists() else None

        if sc_wav:
            try:
                log.info("=" * 60)
                log.info("Uploading to SoundCloud...")
                soundcloud_url = upload_to_soundcloud(sc_wav, concept, sc_cover)
                result["soundcloud_url"] = soundcloud_url
                if soundcloud_url:
                    log.info(f"SoundCloud: {soundcloud_url}")
                else:
                    log.error("SoundCloud upload returned None — run: python main.py soundcloud-login")
                    result["errors"].append("soundcloud: upload returned None (session expired)")
            except Exception as e:
                log.error(f"SoundCloud upload failed: {e}")
                result["errors"].append(f"soundcloud: {e}")
        else:
            log.warning(f"No audio file found for SoundCloud (tried WAV + MP3) — skipping")
            result["errors"].append("soundcloud: no audio file found")
    else:
        log.info(f"Skipping SoundCloud (--only {only})")

    # Summary
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("REUPLOAD DONE! Track uploaded successfully!")
    log.info(f"Track: {track_name}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")
    log.info(f"TuneCore: {result.get('tunecore_url', 'N/A')}")
    log.info(f"SoundCloud: {result.get('soundcloud_url', 'N/A')}")

    return result


def _format_duration(seconds: float) -> str:
    """Format seconds into mm:ss string."""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"


def process_single_track(mp3_path: Path, concept=None) -> dict:
    """Process one compiled MP3 file: concept → thumbnail → video → upload.

    Args:
        mp3_path: Path to the MP3 file.
        concept: Optional pre-generated MusicConcept. If None, generates one.
    """
    ensure_path()
    result = {
        "file": str(mp3_path),
        "concept": None,
        "duration": None,
        "thumbnail_path": None,
        "video_path": None,
        "youtube_url": None,
        "tiktok_url": None,
        "tunecore_url": None,
        "soundcloud_url": None,
        "errors": [],
    }

    # Determine WAV path (audio_merger already creates it alongside MP3)
    wav_path = mp3_path.with_suffix(".wav")

    # Step 1: Detect audio duration (prefer WAV, fall back to MP3)
    audio_path = wav_path if wav_path.exists() else mp3_path
    try:
        log.info("=" * 60)
        log.info(f"STEP 1: Reading audio file: {audio_path.name}")
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", str(audio_path),
            ],
            capture_output=True, text=True,
        )
        duration_sec = float(json.loads(probe.stdout)["format"]["duration"])
        duration_str = _format_duration(duration_sec)
        result["duration"] = duration_str
        log.info(f"Duration: {duration_str} ({duration_sec:.1f} seconds)")
    except Exception as e:
        log.error(f"Failed to read audio: {e}")
        result["errors"].append(f"audio: {e}")
        return result

    # Step 2: Generate concept (or use pre-generated one)
    try:
        if concept is None:
            log.info("=" * 60)
            log.info("STEP 2: Generating music concept...")
            concept = generate_concept()
        result["concept"] = concept.track_name
        log.info(f"Track name: {concept.track_name}")
        log.info(f"Mood: {concept.mood}")
        log.info(f"YouTube title: {concept.youtube_title}")

        # Inject duration into YouTube title
        duration_mins = int(duration_sec) // 60
        if "\U0001f525" in concept.youtube_title:
            concept.youtube_title = concept.youtube_title.replace(
                "\U0001f525", f"\U0001f525 {duration_mins} Minutes of", 1
            )
        concept.youtube_title = concept.youtube_title[:100]

        # Replace {duration} placeholder in description
        concept.youtube_description = concept.youtube_description.replace(
            "{duration}", str(duration_mins)
        )
        concept.youtube_description += f"\n\nDuration: {duration_str}"
    except Exception as e:
        log.error(f"Concept generation failed: {e}")
        result["errors"].append(f"concept: {e}")
        return result

    # Step 3: Generate thumbnail + cover art from ONE DALL-E call (saves API cost)
    cover_path = None
    try:
        log.info("=" * 60)
        log.info("STEP 3: Generating thumbnail + TuneCore cover art (single DALL-E call)...")
        artist_name = DEFAULT_ARTIST
        thumbnail_path, cover_path = generate_thumbnail_and_cover(
            concept.thumbnail_prompt, concept.track_name, artist_name
        )
        result["thumbnail_path"] = str(thumbnail_path)
        result["cover_path"] = str(cover_path)
        log.info(f"Thumbnail: {thumbnail_path}")
        log.info(f"Cover art: {cover_path}")
    except Exception as e:
        log.error(f"Thumbnail generation failed: {e}")
        result["errors"].append(f"thumbnail: {e}")
        return result

    # Step 4: Create video (1920x1080 — works for YouTube & TikTok)
    # Use WAV for better audio quality (ffmpeg re-encodes to AAC anyway)
    try:
        log.info("=" * 60)
        log.info(f"STEP 4: Creating video (1920x1080) with {audio_path.suffix} audio...")
        video = create_video(audio_path, thumbnail_path, concept)
        result["video_path"] = str(video)
        log.info(f"Video: {video}")
    except Exception as e:
        log.error(f"Video creation failed: {e}")
        result["errors"].append(f"video: {e}")
        return result

    # Step 5: Upload to YouTube
    try:
        log.info("=" * 60)
        log.info("STEP 5: Uploading to YouTube...")
        youtube_url = upload_to_youtube(video, thumbnail_path, concept)
        result["youtube_url"] = youtube_url
        if youtube_url:
            log.info(f"YouTube URL: {youtube_url}")
        else:
            log.error("YouTube upload returned None — check client_secrets.json and OAuth token")
            result["errors"].append("youtube: upload returned None (check client_secrets.json / OAuth)")
    except Exception as e:
        log.error(f"YouTube upload failed: {e}")
        result["errors"].append(f"youtube: {e}")

    # Step 6: Upload to TikTok
    try:
        log.info("=" * 60)
        log.info("STEP 6: Uploading to TikTok...")
        tiktok_url = upload_to_tiktok(video, concept)
        result["tiktok_url"] = tiktok_url
        if tiktok_url:
            log.info(f"TikTok: {tiktok_url}")
        else:
            log.error("TikTok upload returned None — check cookies/login above")
            result["errors"].append("tiktok: upload returned None (cookies expired or login redirect)")
    except Exception as e:
        log.error(f"TikTok upload failed: {e}")
        result["errors"].append(f"tiktok: {e}")

    # Step 7: Cover art already generated in Step 3 (combined DALL-E call)
    if not cover_path:
        try:
            log.info("=" * 60)
            log.info("STEP 7: Cover art missing from Step 3 — generating separately...")
            artist_name = DEFAULT_ARTIST
            cover_path = generate_cover_art(
                concept.thumbnail_prompt, concept.track_name, artist_name
            )
            result["cover_path"] = str(cover_path)
            log.info(f"Cover art: {cover_path}")
        except Exception as e:
            log.error(f"Cover art generation failed: {e}")
            result["errors"].append(f"cover_art: {e}")
    else:
        log.info("=" * 60)
        log.info("STEP 7: Cover art already generated in Step 3 — skipping")

    # Step 8: Upload to TuneCore
    if SKIP_TUNECORE:
        log.info("=" * 60)
        log.info("STEP 8: TuneCore SKIPPED (SKIP_TUNECORE=true)")
    elif cover_path and wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("STEP 8: Uploading to TuneCore...")
            tunecore_url = upload_to_tunecore(wav_path, cover_path, concept)
            result["tunecore_url"] = tunecore_url
            if tunecore_url:
                log.info(f"TuneCore: {tunecore_url}")
            else:
                log.error("TuneCore upload returned None — run: python main.py tunecore-login")
                result["errors"].append("tunecore: upload returned None (session expired)")
        except Exception as e:
            log.error(f"TuneCore upload failed: {e}")
            result["errors"].append(f"tunecore: {e}")
    else:
        if not wav_path.exists():
            log.warning(f"WAV file not found ({wav_path}) — skipping TuneCore")
            result["errors"].append(f"tunecore: WAV not found at {wav_path}")
        if not cover_path:
            log.warning("Cover art not generated — skipping TuneCore")

    # Step 9: Upload to SoundCloud (uses same WAV + cover art as TuneCore)
    if SKIP_SOUNDCLOUD:
        log.info("=" * 60)
        log.info("STEP 9: SoundCloud SKIPPED (SKIP_SOUNDCLOUD=true)")
    elif wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("STEP 9: Uploading to SoundCloud...")
            # Use cover art as thumbnail (1600x1600 works well on SoundCloud)
            sc_thumbnail = Path(cover_path) if cover_path else None
            soundcloud_url = upload_to_soundcloud(wav_path, concept, sc_thumbnail)
            result["soundcloud_url"] = soundcloud_url
            if soundcloud_url:
                log.info(f"SoundCloud: {soundcloud_url}")
            else:
                log.error("SoundCloud upload returned None — run: python main.py soundcloud-login")
                result["errors"].append("soundcloud: upload returned None (session expired)")
        except Exception as e:
            log.error(f"SoundCloud upload failed: {e}")
            result["errors"].append(f"soundcloud: {e}")
    else:
        log.warning(f"WAV file not found ({wav_path}) — skipping SoundCloud")
        result["errors"].append(f"soundcloud: WAV not found at {wav_path}")

    # Summary
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("DONE! Track uploaded successfully!")
    log.info(f"Track: {result['concept']}")
    log.info(f"Duration: {result['duration']}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")
    log.info(f"TuneCore: {result.get('tunecore_url', 'N/A')}")
    log.info(f"SoundCloud: {result.get('soundcloud_url', 'N/A')}")

    return result
