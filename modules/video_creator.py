from pathlib import Path
from moviepy import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    vfx,
)
from PIL import ImageFont
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR
from utils.logger import log

# Resolve a usable font at import time. MoviePy's TextClip delegates to
# Pillow, so we probe with ImageFont.truetype to find the first available font.
_FONT_CANDIDATES = [
    "Arial",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "DejaVu-Sans-Bold",
    "Liberation-Sans-Bold",
]


def _resolve_font() -> str:
    for candidate in _FONT_CANDIDATES:
        try:
            ImageFont.truetype(candidate, 20)
            return candidate
        except (OSError, IOError):
            continue
    # Last resort — return a name and let MoviePy try its own lookup
    return "DejaVu-Sans"


_FONT = _resolve_font()


def create_videos(
    audio_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
) -> tuple[Path, Path]:
    log.info(f"Creating videos for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    youtube_path = OUTPUT_DIR / f"{safe_name}_youtube.mp4"
    tiktok_path = OUTPUT_DIR / f"{safe_name}_tiktok.mp4"

    # Load audio
    audio = AudioFileClip(str(audio_path))
    duration = audio.duration

    # --- YouTube video (16:9 @ 1920x1080) ---
    log.info("Creating YouTube video (16:9)...")
    yt_video = _create_landscape_video(thumbnail_path, audio, duration, concept)
    yt_video.write_videofile(
        str(youtube_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    yt_video.close()
    log.info(f"YouTube video saved: {youtube_path}")

    # --- TikTok video (9:16 @ 1080x1920) ---
    log.info("Creating TikTok video (9:16)...")
    tk_video = _create_portrait_video(thumbnail_path, audio, duration, concept)
    tk_video.write_videofile(
        str(tiktok_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    tk_video.close()
    log.info(f"TikTok video saved: {tiktok_path}")

    audio.close()
    return youtube_path, tiktok_path


def _create_landscape_video(
    thumbnail_path: Path,
    audio: AudioFileClip,
    duration: float,
    concept: MusicConcept,
) -> CompositeVideoClip:
    W, H = 1920, 1080

    # Background image with slow zoom (Ken Burns effect)
    bg = (
        ImageClip(str(thumbnail_path))
        .resized((W + 100, H + 60))
        .with_duration(duration)
        .with_position(("center", "center"))
        .resized(lambda t: 1 + 0.03 * (t / duration))  # slow zoom in
    )

    # Track name overlay
    title = (
        TextClip(
            text=concept.track_name,
            font_size=60,
            color="white",
            font=_FONT,
            stroke_color="black",
            stroke_width=2,
        )
        .with_duration(duration)
        .with_position(("center", H - 120))
    )

    # Genre/mood subtitle
    subtitle = (
        TextClip(
            text=f"{concept.genre} | {concept.mood}",
            font_size=30,
            color="#cccccc",
            font=_FONT,
        )
        .with_duration(duration)
        .with_position(("center", H - 60))
    )

    video = CompositeVideoClip([bg, title, subtitle], size=(W, H))
    video = video.with_audio(audio)
    return video


def _create_portrait_video(
    thumbnail_path: Path,
    audio: AudioFileClip,
    duration: float,
    concept: MusicConcept,
) -> CompositeVideoClip:
    W, H = 1080, 1920

    # Background image — center crop to portrait
    bg = (
        ImageClip(str(thumbnail_path))
        .resized(height=H + 100)
        .with_duration(duration)
        .with_position(("center", "center"))
        .resized(lambda t: 1 + 0.03 * (t / duration))
    )

    # Track name overlay
    title = (
        TextClip(
            text=concept.track_name,
            font_size=50,
            color="white",
            font=_FONT,
            stroke_color="black",
            stroke_width=2,
        )
        .with_duration(duration)
        .with_position(("center", H - 250))
    )

    video = CompositeVideoClip([bg, title], size=(W, H))
    video = video.with_audio(audio)
    return video
