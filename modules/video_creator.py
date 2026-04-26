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


def generate_chapters(audio_path: Path, chapter_interval_sec: int = 120) -> str:
    """Generate YouTube chapters (timestamps) from audio using energy analysis.

    Detects energy changes to create meaningful chapter markers.
    Returns a string like:
      0:00 Intro
      2:05 First Drop
      4:10 Deep Groove
      ...
    YouTube auto-creates chapters when description starts with 0:00.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        log.warning("librosa not installed — skipping chapter generation")
        return ""

    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        duration = librosa.get_duration(y=y, sr=sr)

        if duration < 180:
            return ""

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        hop_length = 512

        chapter_labels = [
            "Intro", "Rising Energy", "First Drop", "Deep Groove",
            "Building Up", "Peak Energy", "Breakdown", "Second Wave",
            "Climax", "Tribal Flow", "Hypnotic Phase", "Final Rush",
            "Epic Drop", "Spiritual Groove", "Outro",
        ]

        chapters = []
        chapters.append((0, chapter_labels[0]))

        num_chapters = min(int(duration // chapter_interval_sec), len(chapter_labels) - 2)
        if num_chapters < 2:
            return ""

        segment_len = int(len(onset_env) / (num_chapters + 1))
        for i in range(1, num_chapters + 1):
            start_frame = i * segment_len
            search_start = max(0, start_frame - segment_len // 4)
            search_end = min(len(onset_env), start_frame + segment_len // 4)
            region = onset_env[search_start:search_end]
            peak_frame = search_start + np.argmax(region)
            peak_sec = librosa.frames_to_time(peak_frame, sr=sr, hop_length=hop_length)
            peak_sec = int(peak_sec)
            label = chapter_labels[min(i, len(chapter_labels) - 1)]
            chapters.append((peak_sec, label))

        lines = []
        for sec, label in chapters:
            m, s = divmod(sec, 60)
            lines.append(f"{m}:{s:02d} {label}")

        result = "\n".join(lines)
        log.info(f"Generated {len(chapters)} chapters for {duration:.0f}s track")
        return result
    except Exception as e:
        log.warning(f"Chapter generation failed: {e}")
        return ""


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


def _find_top_segments(audio_path: Path, count: int = 3, segment_sec: int = 45) -> list[float]:
    """Find the top N loudest non-overlapping segments in the audio."""
    duration = _get_audio_duration(audio_path)
    if duration <= segment_sec:
        return [0.0]

    scored = []
    step = 10
    for start in range(0, max(1, int(duration - segment_sec)), step):
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(segment_sec),
            "-i", str(audio_path),
            "-af", "volumedetect",
            "-f", "null", "-",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        for line in r.stderr.splitlines():
            if "mean_volume" in line:
                try:
                    vol = float(line.split("mean_volume:")[1].strip().split()[0])
                    scored.append((start, vol))
                except (ValueError, IndexError):
                    pass

    scored.sort(key=lambda x: x[1], reverse=True)

    selected = []
    for start, vol in scored:
        overlap = any(abs(start - s) < segment_sec for s in selected)
        if not overlap:
            selected.append(start)
        if len(selected) >= count:
            break

    return selected or [0.0]


def _find_loudest_segment(audio_path: Path, segment_sec: int = 45) -> float:
    """Find the start time of the loudest segment in the audio.

    Uses FFmpeg's volumedetect on sliding windows to find the peak section.
    Returns start time in seconds.
    """
    duration = _get_audio_duration(audio_path)
    if duration <= segment_sec:
        return 0.0

    best_start = 0.0
    best_vol = -999.0
    step = 10

    for start in range(0, max(1, int(duration - segment_sec)), step):
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(segment_sec),
            "-i", str(audio_path),
            "-af", "volumedetect",
            "-f", "null", "-",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        for line in r.stderr.splitlines():
            if "mean_volume" in line:
                try:
                    vol = float(line.split("mean_volume:")[1].strip().split()[0])
                    if vol > best_vol:
                        best_vol = vol
                        best_start = float(start)
                except (ValueError, IndexError):
                    pass
    log.info(f"Loudest {segment_sec}s segment starts at {best_start:.0f}s (mean vol: {best_vol:.1f} dB)")
    return best_start


def create_short_video(
    audio_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
    duration_sec: int = 45,
) -> Path:
    """Create a vertical 1080x1920 Short video from the loudest segment.

    Extracts the most energetic segment, crops thumbnail to 9:16 vertical,
    and creates a YouTube Shorts-ready video (under 60 seconds).
    """
    _check_ffmpeg()
    log.info(f"Creating Short video for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]
    short_path = OUTPUT_DIR / f"{safe_name}_short.mp4"

    start = _find_loudest_segment(audio_path, segment_sec=duration_sec)

    import random
    comment_baits = [
        "Comment your city 👇",
        "Drop a 🔥 if you feel this",
        "Tag someone who needs this",
        "What country are you from? 👇",
        "Type YES if you vibed 🎧",
    ]
    bait_text = random.choice(comment_baits)
    safe_bait = bait_text.replace("'", "'\\''").replace(":", "\\:")

    vf_filter = (
        "scale=1920:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "fade=in:0:15,fade=out:st={fade_out}:d=1,"
        "drawtext=text='{bait}':"
        "fontsize=52:fontcolor=white:borderw=3:bordercolor=black:"
        "x=(w-text_w)/2:y=h-180:"
        "enable='between(t,2,8)'"
    ).format(fade_out=duration_sec - 1, bait=safe_bait)

    _run_ffmpeg([
        "-ss", str(start), "-t", str(duration_sec),
        "-i", str(audio_path),
        "-loop", "1", "-i", str(thumbnail_path),
        "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-pix_fmt", "yuv420p",
        str(short_path),
    ], label="short video")

    log.info(f"Short video saved: {short_path} ({duration_sec}s)")
    return short_path


def create_multiple_shorts(
    audio_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
    count: int = 3,
    duration_sec: int = 45,
) -> list[Path]:
    """Create multiple Short videos from different segments of the same track.

    Finds the top N loudest non-overlapping segments and creates a vertical
    Short from each. Returns list of video paths.
    """
    _check_ffmpeg()
    segments = _find_top_segments(audio_path, count=count, segment_sec=duration_sec)
    log.info(f"Creating {len(segments)} Shorts from segments at: {segments}")

    import random
    comment_baits = [
        "Comment your city 👇",
        "Drop a 🔥 if you feel this",
        "Tag someone who needs this",
        "What country are you from? 👇",
        "Type YES if you vibed 🎧",
    ]

    shorts = []
    for i, start in enumerate(segments):
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
        safe_name = safe_name.strip().replace(" ", "_")[:40]
        short_path = OUTPUT_DIR / f"{safe_name}_short_{i + 1}.mp4"

        bait_text = comment_baits[i % len(comment_baits)]
        safe_bait = bait_text.replace("'", "'\\''").replace(":", "\\:")

        vf_filter = (
            "scale=1920:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "fade=in:0:15,fade=out:st={fade_out}:d=1,"
            "drawtext=text='{bait}':"
            "fontsize=52:fontcolor=white:borderw=3:bordercolor=black:"
            "x=(w-text_w)/2:y=h-180:"
            "enable='between(t,2,8)'"
        ).format(fade_out=duration_sec - 1, bait=safe_bait)

        _run_ffmpeg([
            "-ss", str(start), "-t", str(duration_sec),
            "-i", str(audio_path),
            "-loop", "1", "-i", str(thumbnail_path),
            "-vf", vf_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-pix_fmt", "yuv420p",
            str(short_path),
        ], label=f"short video {i + 1}/{len(segments)}")

        shorts.append(short_path)
        log.info(f"Short {i + 1} saved: {short_path}")

    return shorts
