"""Create a 1920x1080 video from a thumbnail image + audio using FFmpeg.

Single video works for both YouTube and TikTok.
Uses FFmpeg directly — a static image is looped over the audio duration.
"""

import subprocess
import shutil
from pathlib import Path

from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR
from utils.logger import log


def _check_ffmpeg():
    """Verify FFmpeg is available (checks PATH and local bin/)."""
    from utils.auto_setup import ensure_path
    ensure_path()
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
        timeout=600,  # 10 min max
    )
    if result.returncode != 0:
        log.error(f"FFmpeg stderr: {result.stderr[-500:]}")
        raise RuntimeError(f"FFmpeg failed for {label}: {result.stderr[-200:]}")


def create_video(
    audio_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
) -> Path:
    """Create a 1920x1080 video from image + audio (works for YouTube & TikTok)."""
    _check_ffmpeg()
    log.info(f"Creating video for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    video_path = OUTPUT_DIR / f"{safe_name}_video.mp4"

    # --- YouTube format (16:9 @ 1920x1080) — works on TikTok too ---
    log.info("Creating video (1920x1080)...")
    _run_ffmpeg(
        [
            "-loop", "1",
            "-framerate", "2",
            "-i", str(thumbnail_path),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-preset", "ultrafast",
            "-crf", "28",
            "-r", "2",
            "-c:a", "aac",
            "-b:a", "192k",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            str(video_path),
        ],
        label="video",
    )
    log.info(f"Video saved: {video_path}")

    return video_path
