"""Merge multiple MP3 files into one continuous track using FFmpeg."""

import json
import re
import subprocess
import shutil
import tempfile
from pathlib import Path

from config import OUTPUT_DIR
from utils.logger import log

TUNECORE_MIN_DURATION_SEC = 65


def get_duration(audio_path: Path) -> float:
    """Return duration in seconds of an audio file (MP3/WAV)."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(json.loads(probe.stdout)["format"]["duration"])
    except Exception as e:
        log.warning(f"Could not probe duration for {audio_path}: {e}")
        return 0.0


def trim_silence(audio_path: Path) -> Path:
    """Strip silence from start, end, AND middle of an audio file in-place.

    Uses ffmpeg's silenceremove filter in three passes:
    - Leading: remove silence below -50 dB
    - Middle: collapse ANY silence longer than 2.5 s (below -50 dB) to
      0.5 s — keeps musical breathing room but stays well under TuneCore's
      5 s rejection threshold
    - Trailing: reverse → remove leading silence → reverse back

    Returns the same path (overwritten). On failure, the original file is
    left untouched and a warning is logged.
    """
    if not audio_path.exists():
        return audio_path

    tmp_path = audio_path.with_suffix(f".trimmed{audio_path.suffix}")

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-af", (
                # Strip leading silence + collapse ALL mid-track silences
                # (stop_periods=-1) down to 0.5 s each — well under TuneCore's
                # 5 s rejection threshold.
                "silenceremove="
                "start_periods=1:start_duration=0.1:start_threshold=-50dB:"
                "stop_periods=-1:stop_duration=0.5:stop_threshold=-50dB,"
                # Strip trailing silence (reverse → trim leading → reverse back)
                "areverse,"
                "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB,"
                "areverse"
            ),
            str(tmp_path),
        ],
        capture_output=True, text=True, timeout=300,
    )

    if result.returncode != 0:
        log.warning(f"Silence trim failed: {result.stderr[-200:]}")
        tmp_path.unlink(missing_ok=True)
        return audio_path

    before = get_duration(audio_path)
    after = get_duration(tmp_path)
    trimmed = before - after

    if trimmed > 0.5:
        shutil.move(str(tmp_path), str(audio_path))
        log.info(f"Trimmed {trimmed:.1f}s of silence from {audio_path.name} "
                 f"({before:.1f}s → {after:.1f}s)")
    else:
        tmp_path.unlink(missing_ok=True)
        log.info(f"No significant silence found in {audio_path.name}")

    return audio_path


def is_tunecore_ready(audio_path: Path) -> bool:
    """Return True if the audio meets TuneCore requirements (≥60s, no long silence)."""
    dur = get_duration(audio_path)
    if dur < TUNECORE_MIN_DURATION_SEC:
        log.warning(
            f"TuneCore: {audio_path.name} is only {dur:.1f}s — "
            f"minimum is {TUNECORE_MIN_DURATION_SEC}s for singles. Skipping TuneCore."
        )
        return False
    return True


def wav_from_mp3(mp3_path: Path) -> Path:
    """Ensure a PCM WAV exists next to `mp3_path` (same stem, .wav extension).

    Used by split-upload mode where we skip merging but still need a WAV for
    TuneCore / SoundCloud. Returns the WAV path whether newly created or
    already present.
    """
    wav_path = mp3_path.with_suffix(".wav")
    if wav_path.exists():
        return wav_path
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found — required for WAV export")
    log.info(f"Exporting WAV: {wav_path}")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path),
         "-acodec", "pcm_s16le", str(wav_path)],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        log.warning(f"WAV export failed: {result.stderr[-200:]}")
    return wav_path


def merge_mp3s(mp3_files: list[Path], output_name: str = "merged") -> Path:
    """Merge multiple MP3 files into one continuous track (no gaps).

    Uses FFmpeg concat demuxer — no moviepy/imageio dependency needed.

    Args:
        mp3_files: List of MP3 file paths to merge.
        output_name: Name for the output file (without extension).

    Returns:
        Path to the merged MP3 file.
    """
    if not mp3_files:
        raise ValueError("No MP3 files provided")

    if len(mp3_files) == 1:
        log.info("Only 1 MP3 file, no merging needed")
        single = mp3_files[0]
        wav_path = OUTPUT_DIR / f"{single.stem}.wav"
        if not wav_path.exists():
            log.info(f"Exporting WAV for TuneCore: {wav_path}")
            wav_result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(single),
                 "-acodec", "pcm_s16le", str(wav_path)],
                capture_output=True, text=True, timeout=600,
            )
            if wav_result.returncode == 0:
                log.info(f"WAV saved: {wav_path}")
                trim_silence(wav_path)
            else:
                log.warning(f"WAV export failed: {wav_result.stderr[-200:]}")
        return single

    from utils.auto_setup import ensure_path
    ensure_path()

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found — required for merging MP3 files")

    log.info(f"Merging {len(mp3_files)} MP3 files back to back (no gaps)...")

    # Build FFmpeg concat list file
    concat_file = Path(tempfile.mktemp(suffix=".txt", prefix="luth_concat_"))
    try:
        with open(concat_file, "w", encoding="utf-8") as f:
            for i, mp3_path in enumerate(mp3_files):
                log.info(f"  [{i + 1}/{len(mp3_files)}]: {mp3_path.name}")
                # FFmpeg concat format: file 'path' (escape single quotes)
                escaped = str(mp3_path.resolve()).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in output_name)
        safe_name = safe_name.strip().replace(" ", "_")[:50] or "merged"
        output_path = OUTPUT_DIR / f"{safe_name}.mp3"

        # Merge using FFmpeg concat demuxer
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:a", "libmp3lame",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            log.error(f"FFmpeg merge stderr: {result.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg merge failed: {result.stderr[-200:]}")

        # Log duration
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(output_path)],
                capture_output=True, text=True, timeout=30,
            )
            import json
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            mins = int(duration) // 60
            secs = int(duration) % 60
            log.info(f"Merged duration: {mins}:{secs:02d} ({duration:.1f} seconds)")
        except Exception:
            pass

        # Also export WAV for TuneCore distribution
        wav_path = output_path.with_suffix(".wav")
        log.info(f"Exporting WAV for TuneCore: {wav_path}")
        wav_result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(output_path),
             "-acodec", "pcm_s16le", str(wav_path)],
            capture_output=True, text=True, timeout=600,
        )
        if wav_result.returncode == 0:
            log.info(f"WAV saved: {wav_path}")
            trim_silence(wav_path)
        else:
            log.warning(f"WAV export failed: {wav_result.stderr[-200:]}")

        log.info(f"Merged MP3 saved: {output_path}")
        return output_path

    finally:
        concat_file.unlink(missing_ok=True)


def merge_mp3s_crossfade(mp3_files: list[Path], output_name: str = "merged",
                          crossfade_sec: float = 3.0) -> Path:
    """Merge MP3s with smooth crossfade transitions between segments.

    Uses FFmpeg's acrossfade filter chained in cascade. Falls back to
    plain concat (merge_mp3s) when there's only 1 file or crossfade is 0.

    Returns Path to the merged MP3 (same naming as merge_mp3s).
    """
    if not mp3_files:
        raise ValueError("No MP3 files provided")
    if len(mp3_files) == 1 or crossfade_sec <= 0:
        return merge_mp3s(mp3_files, output_name=output_name)

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg not found — required for crossfade merge")

    log.info(f"Merging {len(mp3_files)} MP3s with {crossfade_sec}s crossfade...")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in output_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50] or "merged"
    output_path = OUTPUT_DIR / f"{safe_name}.mp3"

    inputs = []
    for mp3 in mp3_files:
        inputs.extend(["-i", str(mp3)])

    n = len(mp3_files)
    filter_parts = []
    last_label = "[0:a]"
    for i in range(1, n):
        in_b = f"[{i}:a]"
        out_label = f"[a{i}]"
        filter_parts.append(
            f"{last_label}{in_b}acrossfade=d={crossfade_sec}:c1=tri:c2=tri{out_label}"
        )
        last_label = out_label

    filter_complex = ";".join(filter_parts)

    result = subprocess.run(
        ["ffmpeg", "-y", *inputs,
         "-filter_complex", filter_complex,
         "-map", last_label,
         "-c:a", "libmp3lame", "-b:a", "192k",
         str(output_path)],
        capture_output=True, text=True, timeout=1800,
    )

    if result.returncode != 0:
        log.warning(f"Crossfade merge failed ({result.stderr[-300:]}), falling back to concat")
        return merge_mp3s(mp3_files, output_name=output_name)

    duration = get_duration(output_path)
    mins = int(duration) // 60
    secs = int(duration) % 60
    log.info(f"Crossfade merged: {mins}:{secs:02d} ({duration:.1f}s) → {output_path}")

    wav_path = output_path.with_suffix(".wav")
    log.info(f"Exporting WAV: {wav_path}")
    wav_result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(output_path),
         "-acodec", "pcm_s16le", str(wav_path)],
        capture_output=True, text=True, timeout=600,
    )
    if wav_result.returncode == 0:
        log.info(f"WAV saved: {wav_path}")
        trim_silence(wav_path)
    else:
        log.warning(f"WAV export failed: {wav_result.stderr[-200:]}")

    return output_path


def trim_quiet_intro(mp3_path: Path, threshold_db: float = -30,
                     max_check_sec: float = 15) -> Path:
    """Detect and trim quiet intros (audio present but very low volume).

    Different from trim_silence() which targets actual silence (-50 dB).
    This targets intros where audio exists but is too quiet to hook
    listeners (below threshold_db for the first max_check_sec seconds).

    Returns the same path (trimmed in-place) or original if no quiet intro.
    """
    if not mp3_path.exists():
        return mp3_path

    result = subprocess.run(
        ["ffmpeg", "-i", str(mp3_path), "-t", str(max_check_sec),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )

    match = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
    if not match:
        return mp3_path

    mean_vol = float(match.group(1))
    if mean_vol >= threshold_db:
        return mp3_path

    log.info(f"Quiet intro detected in {mp3_path.name}: {mean_vol:.1f} dB "
             f"(threshold {threshold_db} dB) — trimming first {max_check_sec}s")

    tmp_path = mp3_path.with_suffix(".trimintro.mp3")
    trim_result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path),
         "-ss", str(max_check_sec), "-c", "copy", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )
    if trim_result.returncode == 0 and tmp_path.exists():
        shutil.move(str(tmp_path), str(mp3_path))
        log.info(f"Trimmed {max_check_sec}s quiet intro from {mp3_path.name}")
    else:
        tmp_path.unlink(missing_ok=True)
        log.warning(f"Intro trim failed for {mp3_path.name}")

    return mp3_path
