"""Create YouTube and TikTok videos from a thumbnail image + audio using FFmpeg.

Uses FFmpeg directly instead of MoviePy for dramatically faster rendering.
A static image is looped over the audio duration — simple and fast.
"""

import subprocess
import shutil
from pathlib import Path

from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR
from utils.logger import log


def _check_ffmpeg():
    """Verify FFmpeg is available."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg not found. Install it:\n"
            "  Windows: winget install FFmpeg  (or download from ffmpeg.org)\n"
            "  Linux:   sudo apt install ffmpeg\n"
            "  macOS:   brew install ffmpeg"
        )


def _run_ffmpeg(args: list[str], label: str):
    """Run an FFmpeg command and handle errors."""
    cmd = ["ffmpeg", "-y"] + args
    log.info(f"Running FFmpeg for {label}...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5 min max
    )
    if result.returncode != 0:
        log.error(f"FFmpeg stderr: {result.stderr[-500:]}")
        raise RuntimeError(f"FFmpeg failed for {label}: {result.stderr[-200:]}")


def create_videos(
    audio_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
) -> tuple[Path, Path]:
    """Create YouTube (16:9) and TikTok (9:16) videos from image + audio."""
    _check_ffmpeg()
    log.info(f"Creating videos for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    youtube_path = OUTPUT_DIR / f"{safe_name}_youtube.mp4"
    tiktok_path = OUTPUT_DIR / f"{safe_name}_tiktok.mp4"

    # --- YouTube video (16:9 @ 1920x1080) ---
    log.info("Creating YouTube video (16:9)...")
    _run_ffmpeg(
        [
            "-loop", "1",
            "-i", str(thumbnail_path),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            str(youtube_path),
        ],
        label="YouTube video",
    )
    log.info(f"YouTube video saved: {youtube_path}")

    # --- TikTok video (9:16 @ 1080x1920) ---
    log.info("Creating TikTok video (9:16)...")
    _run_ffmpeg(
        [
            "-loop", "1",
            "-i", str(thumbnail_path),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            str(tiktok_path),
        ],
        label="TikTok video",
    )
    log.info(f"TikTok video saved: {tiktok_path}")

    return youtube_path, tiktok_path
