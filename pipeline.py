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


def run_pipeline() -> dict:
    """Run the full music content pipeline. Returns a summary dict."""
    result = {
        "concept": None,
        "audio_path": None,
        "duration": None,
        "thumbnail_path": None,
        "youtube_video_path": None,
        "tiktok_video_path": None,
        "youtube_url": None,
        "tiktok_url": None,
        "errors": [],
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
        result["audio_path"] = str(audio_path)

        # Detect audio duration
        audio_clip = AudioFileClip(str(audio_path))
        duration_sec = audio_clip.duration
        audio_clip.close()
        duration_str = _format_duration(duration_sec)
        result["duration"] = duration_str

        log.info(f"Audio: {audio_path}")
        log.info(f"Duration: {duration_str} ({duration_sec:.1f} seconds)")

        # Add duration to YouTube description
        concept.youtube_description += f"\n\nDuration: {duration_str}"
    except Exception as e:
        log.error(f"Music generation failed: {e}")
        result["errors"].append(f"music: {e}")
        return result

    # Step 3: Generate thumbnail
    try:
        log.info("=" * 60)
        log.info("STEP 3: Generating thumbnail with DALL-E 3...")
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
        log.info("STEP 4: Creating YouTube and TikTok videos...")
        youtube_video, tiktok_video = create_videos(audio_path, thumbnail_path, concept)
        result["youtube_video_path"] = str(youtube_video)
        result["tiktok_video_path"] = str(tiktok_video)
        log.info(f"YouTube video: {youtube_video}")
        log.info(f"TikTok video: {tiktok_video}")
    except Exception as e:
        log.error(f"Video creation failed: {e}")
        result["errors"].append(f"video: {e}")
        return result

    # Step 5: Upload to YouTube
    try:
        log.info("=" * 60)
        log.info("STEP 5: Uploading to YouTube...")
        youtube_url = upload_to_youtube(youtube_video, thumbnail_path, concept)
        result["youtube_url"] = youtube_url
    except Exception as e:
        log.error(f"YouTube upload failed: {e}")
        result["errors"].append(f"youtube: {e}")

    # Step 6: Upload to TikTok
    try:
        log.info("=" * 60)
        log.info("STEP 6: Uploading to TikTok...")
        tiktok_url = upload_to_tiktok(tiktok_video, concept)
        result["tiktok_url"] = tiktok_url
    except Exception as e:
        log.error(f"TikTok upload failed: {e}")
        result["errors"].append(f"tiktok: {e}")

    # Summary
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Pipeline completed with errors: {result['errors']}")
    else:
        log.info("Pipeline completed successfully!")
    log.info(f"Track: {result['concept']}")
    log.info(f"Duration: {result.get('duration', 'N/A')}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")

    return result
