"""Create a 1920x1080 video from a thumbnail image + audio using FFmpeg.

Single video works for both YouTube and TikTok.
Supports beat-synced visual effects (zoom pulses, brightness flashes, slow drift)
when librosa is available, with automatic fallback to static image loop.
"""

import subprocess
import shutil
from pathlib import Path

from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, BEAT_SYNC_VIDEO, VIDEO_FPS
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


def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


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


def _analyze_beats(audio_path: Path) -> list[float] | None:
    """Detect beat timestamps using librosa.

    Returns list of beat times in seconds, or None on failure.
    """
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        if len(beat_times) < 2:
            log.warning("Too few beats detected, skipping beat sync")
            return None
        tempo_val = float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo)
        log.info(f"Detected {len(beat_times)} beats at ~{tempo_val:.0f} BPM")
        return beat_times
    except ImportError:
        log.warning("librosa not installed — falling back to static video")
        return None
    except Exception as e:
        log.warning(f"Beat detection failed: {e} — falling back to static video")
        return None


def _build_beat_filter(
    beat_times: list[float], duration: float, fps: int = 24,
) -> str:
    """Build FFmpeg filter chain with zoom pulses and beat-synced eq flashes.

    Both zoom and brightness/saturation use periodic mathematical expressions
    derived from tempo, avoiding the need for sendcmd temp files (which break
    on Windows due to path escaping issues).

    Returns the complete filter string.
    """
    # Derive tempo-based period for zoom (60 / BPM in frames)
    intervals = [beat_times[i + 1] - beat_times[i] for i in range(len(beat_times) - 1)]
    median_interval = sorted(intervals)[len(intervals) // 2]
    bpm = 60.0 / median_interval
    beat_period_sec = 60.0 / bpm  # same as median_interval, but explicit
    period = beat_period_sec * fps  # beat period in frames
    first_beat = beat_times[0] * fps  # first beat in frames

    # --- Zoompan: zoom pulse 1.0 → 1.05 using tempo-derived period ---
    zoom_expr = (
        f"1.0+0.05*max(0\\,1-3.0*mod(on-{first_beat:.1f}\\,{period:.1f})/{period:.1f})"
    )
    drift_x = f"iw/2-(iw/zoom/2)+iw*0.025*sin(on/500)"
    center_y = f"ih/2-(ih/zoom/2)"

    zoompan = (
        f"zoompan=z={zoom_expr}"
        f":x='{drift_x}'"
        f":y='{center_y}'"
        f":d={int(duration * fps)}:s=1920x1080:fps={fps}"
    )

    # --- eq filter: brightness/saturation pulse using same BPM period ---
    # Uses the same periodic decay as zoom: flash on beat, decay over ~1/3 period
    beat_fn = f"max(0\\,1-3.0*mod(n-{first_beat:.1f}\\,{period:.1f})/{period:.1f})"
    eq_filter = (
        f"eq=brightness='0.06*{beat_fn}'"
        f":saturation='1+0.2*{beat_fn}'"
        f":eval=frame"
    )

    return f"{zoompan},{eq_filter},format=yuv420p"


def _create_static_video(audio_path: Path, thumbnail_path: Path, video_path: Path):
    """Create a static image loop video (original fallback method)."""
    log.info("Creating static video (1920x1080, 2fps)...")
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
        label="static video",
    )


def _create_beat_synced_video(
    audio_path: Path, thumbnail_path: Path, video_path: Path,
    beat_times: list[float], fps: int = 24,
):
    """Create a beat-synced video with zoom pulses and brightness/saturation flashes."""
    log.info(f"Creating beat-synced video (1920x1080, {fps}fps)...")
    duration = _get_audio_duration(audio_path)
    vf = _build_beat_filter(beat_times, duration, fps)

    full_filter = f"[0:v]{vf}[v]"
    _run_ffmpeg(
        [
            "-i", str(thumbnail_path),
            "-i", str(audio_path),
            "-filter_complex", full_filter,
            "-map", "[v]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(video_path),
        ],
        label="beat-synced video",
    )


def create_video(
    audio_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
) -> Path:
    """Create a 1920x1080 video from image + audio (works for YouTube & TikTok).

    When BEAT_SYNC_VIDEO is enabled and librosa is available, creates a dynamic
    video with zoom pulses, brightness flashes, and slow drift synced to the
    audio's beat. Falls back to static image loop on any failure.
    """
    _check_ffmpeg()
    log.info(f"Creating video for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    video_path = OUTPUT_DIR / f"{safe_name}_video.mp4"

    # Attempt beat-synced video if enabled
    if BEAT_SYNC_VIDEO:
        beat_times = _analyze_beats(audio_path)
        if beat_times:
            try:
                _create_beat_synced_video(
                    audio_path, thumbnail_path, video_path, beat_times, VIDEO_FPS
                )
                log.info(f"Video saved: {video_path}")
                return video_path
            except Exception as e:
                log.warning(f"Beat-synced video failed ({e}), falling back to static")

    # Fallback: static image loop
    _create_static_video(audio_path, thumbnail_path, video_path)
    log.info(f"Video saved: {video_path}")
    return video_path
