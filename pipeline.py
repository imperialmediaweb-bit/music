import json
import subprocess
from pathlib import Path

from utils.logger import log
from modules.concept_generator import generate_concept
from modules.thumbnail_generator import generate_thumbnail
from modules.video_creator import create_videos
from modules.youtube_uploader import upload_to_youtube
from modules.tiktok_uploader import upload_to_tiktok


def reupload_track(track_name: str) -> dict:
    """Re-upload an existing track to YouTube and TikTok (skip generation/video steps).

    Looks for existing files in OUTPUT_DIR:
      - {track_name}_youtube.mp4
      - {track_name}_tiktok.mp4
      - {track_name}_thumbnail.png
      - {track_name}.mp3  (for duration detection)

    Regenerates concept metadata (title, description, tags) via OpenAI,
    then uploads to both platforms.
    """
    from config import OUTPUT_DIR
    from modules.concept_generator import generate_concept

    result = {
        "concept": track_name,
        "duration": None,
        "youtube_url": None,
        "tiktok_url": None,
        "errors": [],
    }

    # Locate existing files
    youtube_video = OUTPUT_DIR / f"{track_name}_youtube.mp4"
    tiktok_video = OUTPUT_DIR / f"{track_name}_tiktok.mp4"
    thumbnail = OUTPUT_DIR / f"{track_name}_thumbnail.png"
    mp3_file = OUTPUT_DIR / f"{track_name}.mp3"

    if not thumbnail.exists():
        log.warning(f"Thumbnail not found: {thumbnail} — continuing without it")

    if not youtube_video.exists():
        log.info(f"YouTube video not found: {youtube_video} — skipping (YouTube upload disabled)")

    if not tiktok_video.exists():
        log.warning(f"TikTok video not found: {tiktok_video} — will skip TikTok upload")

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

    # YouTube upload disabled — video was already posted twice
    # To re-enable: uncomment the upload_to_youtube call below
    # try:
    #     youtube_url = upload_to_youtube(youtube_video, thumbnail, concept)
    #     result["youtube_url"] = youtube_url
    # except Exception as e:
    #     result["errors"].append(f"youtube: {e}")

    # Upload to TikTok
    if tiktok_video.exists():
        try:
            log.info("=" * 60)
            log.info("Uploading to TikTok...")
            tiktok_url = upload_to_tiktok(tiktok_video, concept)
            result["tiktok_url"] = tiktok_url
            log.info(f"TikTok URL: {tiktok_url}")
        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            result["errors"].append(f"tiktok: {e}")
    else:
        log.warning("Skipping TikTok upload (no video file)")

    # Summary
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("REUPLOAD DONE! Track uploaded successfully!")
    log.info(f"Track: {track_name}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")

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
    result = {
        "file": str(mp3_path),
        "concept": None,
        "duration": None,
        "thumbnail_path": None,
        "youtube_video_path": None,
        "tiktok_video_path": None,
        "youtube_url": None,
        "tiktok_url": None,
        "errors": [],
    }

    # Step 1: Detect audio duration
    try:
        log.info("=" * 60)
        log.info(f"STEP 1: Reading audio file: {mp3_path.name}")
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", str(mp3_path),
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
            log.info("STEP 2: Generating Afro House concept...")
            concept = generate_concept()
        result["concept"] = concept.track_name
        log.info(f"Track name: {concept.track_name}")
        log.info(f"Mood: {concept.mood}")
        log.info(f"YouTube title: {concept.youtube_title}")

        # Inject duration into YouTube title (e.g. "KAMUZI 🔥 Primal..." → "KAMUZI 🔥 30 Minutes of Primal...")
        duration_mins = int(duration_sec) // 60
        if "🔥" in concept.youtube_title:
            concept.youtube_title = concept.youtube_title.replace(
                "🔥", f"🔥 {duration_mins} Minutes of", 1
            )
        concept.youtube_title = concept.youtube_title[:100]  # Ensure max 100 chars

        # Replace {duration} placeholder in description (if AI used it)
        concept.youtube_description = concept.youtube_description.replace(
            "{duration}", str(duration_mins)
        )

        # Add duration to YouTube description
        concept.youtube_description += f"\n\nDuration: {duration_str}"
    except Exception as e:
        log.error(f"Concept generation failed: {e}")
        result["errors"].append(f"concept: {e}")
        return result

    # Step 3: Generate thumbnail (African mask + track name)
    try:
        log.info("=" * 60)
        log.info("STEP 3: Generating African mask thumbnail...")
        thumbnail_path = generate_thumbnail(concept.thumbnail_prompt, concept.track_name)
        result["thumbnail_path"] = str(thumbnail_path)
        log.info(f"Thumbnail: {thumbnail_path}")
    except Exception as e:
        log.error(f"Thumbnail generation failed: {e}")
        result["errors"].append(f"thumbnail: {e}")
        return result

    # Step 4: Create videos
    try:
        log.info("=" * 60)
        log.info("STEP 4: Creating YouTube + TikTok videos...")
        youtube_video, tiktok_video = create_videos(mp3_path, thumbnail_path, concept)
        result["youtube_video_path"] = str(youtube_video)
        result["tiktok_video_path"] = str(tiktok_video)
        log.info(f"YouTube video: {youtube_video}")
        log.info(f"TikTok video: {tiktok_video}")
    except Exception as e:
        log.error(f"Video creation failed: {e}")
        result["errors"].append(f"video: {e}")
        return result

    # Step 5: YouTube upload disabled — video was already posted twice
    # To re-enable: uncomment the upload_to_youtube call below
    # try:
    #     youtube_url = upload_to_youtube(youtube_video, thumbnail_path, concept)
    #     result["youtube_url"] = youtube_url
    # except Exception as e:
    #     result["errors"].append(f"youtube: {e}")

    # Step 6: Upload to TikTok
    try:
        log.info("=" * 60)
        log.info("STEP 6: Uploading to TikTok...")
        tiktok_url = upload_to_tiktok(tiktok_video, concept)
        result["tiktok_url"] = tiktok_url
        log.info(f"TikTok URL: {tiktok_url}")
    except Exception as e:
        log.error(f"TikTok upload failed: {e}")
        result["errors"].append(f"tiktok: {e}")

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

    return result
