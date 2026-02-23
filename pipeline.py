from pathlib import Path
from moviepy import AudioFileClip

from utils.logger import log
from modules.concept_generator import generate_concept
from modules.music_generator import generate_music
from modules.thumbnail_generator import generate_thumbnail
from modules.video_creator import create_videos
from modules.youtube_uploader import upload_to_youtube
from modules.tiktok_uploader import upload_to_tiktok


def _format_duration(seconds: float) -> str:
    """Format seconds into mm:ss string."""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"


def _process_audio(audio_path: Path, concept, result: dict):
    """Common steps after we have an audio file: detect duration, thumbnail, video, upload."""

    # Detect audio duration
    audio_clip = AudioFileClip(str(audio_path))
    duration_sec = audio_clip.duration
    audio_clip.close()
    duration_str = _format_duration(duration_sec)
    result["audio_path"] = str(audio_path)
    result["duration"] = duration_str

    log.info(f"Audio: {audio_path}")
    log.info(f"Duration: {duration_str} ({duration_sec:.1f} seconds)")

    # Add duration to YouTube description
    concept.youtube_description += f"\n\nDuration: {duration_str}"

    # Generate thumbnail
    log.info("=" * 60)
    log.info("STEP: Generating thumbnail with DALL-E 3...")
    thumbnail_path = generate_thumbnail(concept.thumbnail_prompt, concept.track_name)
    result["thumbnail_path"] = str(thumbnail_path)
    log.info(f"Thumbnail: {thumbnail_path}")

    # Create videos
    log.info("=" * 60)
    log.info("STEP: Creating YouTube and TikTok videos...")
    youtube_video, tiktok_video = create_videos(audio_path, thumbnail_path, concept)
    result["youtube_video_path"] = str(youtube_video)
    result["tiktok_video_path"] = str(tiktok_video)
    log.info(f"YouTube video: {youtube_video}")
    log.info(f"TikTok video: {tiktok_video}")

    # Upload to YouTube
    log.info("=" * 60)
    log.info("STEP: Uploading to YouTube...")
    try:
        youtube_url = upload_to_youtube(youtube_video, thumbnail_path, concept)
        result["youtube_url"] = youtube_url
    except Exception as e:
        log.error(f"YouTube upload failed: {e}")
        result["errors"].append(f"youtube: {e}")

    # Upload to TikTok
    log.info("=" * 60)
    log.info("STEP: Uploading to TikTok...")
    try:
        tiktok_url = upload_to_tiktok(tiktok_video, concept)
        result["tiktok_url"] = tiktok_url
    except Exception as e:
        log.error(f"TikTok upload failed: {e}")
        result["errors"].append(f"tiktok: {e}")


def run_pipeline() -> dict:
    """Run the full pipeline: generate concept, music, thumbnail, video, upload."""
    result = {
        "concept": None, "audio_path": None, "duration": None,
        "thumbnail_path": None, "youtube_video_path": None,
        "tiktok_video_path": None, "youtube_url": None,
        "tiktok_url": None, "errors": [],
    }

    # Step 1: Generate concept
    try:
        log.info("=" * 60)
        log.info("STEP 1: Generating music concept...")
        concept = generate_concept()
        result["concept"] = concept.track_name
        log.info(f"Concept: {concept.track_name} ({concept.genre}, {concept.mood})")
    except Exception as e:
        log.error(f"Concept generation failed: {e}")
        result["errors"].append(f"concept: {e}")
        return result

    # Step 2: Generate music
    try:
        log.info("=" * 60)
        log.info("STEP 2: Generating music on aimusicfactory.ai...")
        audio_path = generate_music(concept)
    except Exception as e:
        log.error(f"Music generation failed: {e}")
        result["errors"].append(f"music: {e}")
        return result

    # Steps 3-6: Process audio (duration, thumbnail, video, upload)
    try:
        _process_audio(audio_path, concept, result)
    except Exception as e:
        log.error(f"Processing failed: {e}")
        result["errors"].append(f"processing: {e}")

    _log_summary(result)
    return result


def process_existing_files(mp3_files: list[Path]) -> list[dict]:
    """Process existing MP3 files: generate concept, thumbnail, video, upload for each."""
    results = []

    for i, mp3_path in enumerate(mp3_files, 1):
        log.info(f"\n{'#' * 60}")
        log.info(f"PROCESSING FILE {i}/{len(mp3_files)}: {mp3_path.name}")
        log.info(f"{'#' * 60}")

        result = {
            "concept": None, "audio_path": str(mp3_path), "duration": None,
            "thumbnail_path": None, "youtube_video_path": None,
            "tiktok_video_path": None, "youtube_url": None,
            "tiktok_url": None, "errors": [],
        }

        # Generate concept for this track
        try:
            log.info("=" * 60)
            log.info("STEP 1: Generating music concept...")
            concept = generate_concept()
            result["concept"] = concept.track_name
            log.info(f"Concept: {concept.track_name} ({concept.genre}, {concept.mood})")
        except Exception as e:
            log.error(f"Concept generation failed: {e}")
            result["errors"].append(f"concept: {e}")
            results.append(result)
            continue

        # Process the MP3 (duration, thumbnail, video, upload)
        try:
            _process_audio(mp3_path, concept, result)
        except Exception as e:
            log.error(f"Processing failed: {e}")
            result["errors"].append(f"processing: {e}")

        _log_summary(result)
        results.append(result)

    return results


def _log_summary(result: dict):
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("Completed successfully!")
    log.info(f"Track: {result['concept']}")
    log.info(f"Duration: {result.get('duration', 'N/A')}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")
