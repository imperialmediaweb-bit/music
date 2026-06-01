"""Audio mastering chain for AI-generated tracks.

Applies a streaming-grade master to merged MP3s before they hit YouTube
and Bandcamp. Targets -14 LUFS integrated (Spotify/YouTube standard) so
the track lands at the same perceived loudness as commercial releases
on the listener's queue.

The chain (in order):
  1. High-pass at 25 Hz — kill DC and inaudible sub rumble
  2. Gentle low-shelf at 80 Hz (+2 dB) — warmth and sub presence
  3. Gentle high-shelf at 10 kHz (+1.5 dB) — "air" on top
  4. Mid/side stereo widening — wider highs, mono bass
  5. EBU R128 two-pass loudness normalization to -14 LUFS, -1.5 dBTP
  6. Output as 320 kbps CBR MP3 (and 44.1 kHz WAV mirror)

Single public entry point: `master_track(path) -> Path`.
"""

import json
import re
import subprocess
from pathlib import Path

from utils.logger import log


TARGET_LUFS = -14.0
TARGET_TP = -1.5
TARGET_LRA = 11.0

EQ_FILTERS = (
    "highpass=f=25,"
    "equalizer=f=80:width_type=q:w=0.9:g=2,"
    "equalizer=f=10000:width_type=q:w=0.7:g=1.5,"
    "stereotools=mlev=0.95:slev=1.15"
)


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _measure_loudness(src: Path) -> dict | None:
    """First pass: measure integrated loudness, true peak and LRA."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
        "-af", f"{EQ_FILTERS},loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        log.warning(f"Loudness measure failed: {result.stderr[-300:]}")
        return None
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr)
    if not match:
        log.warning("Could not parse loudnorm JSON from ffmpeg output")
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        log.warning(f"loudnorm JSON parse error: {e}")
        return None


def master_track(src: Path) -> Path:
    """Apply mastering chain and return the mastered MP3 path.

    Writes alongside the source as `<name>_master.mp3` plus a
    `<name>_master.wav` mirror. Returns the source path unchanged if
    ffmpeg or the loudness probe is unavailable, so the pipeline
    degrades gracefully.
    """
    if not _ffmpeg_available():
        log.warning("Mastering skipped — ffmpeg not found")
        return src

    log.info(f"Mastering: {src.name}")
    measured = _measure_loudness(src)
    if not measured:
        log.warning("Mastering skipped — loudness measurement failed")
        return src

    out_mp3 = src.with_name(f"{src.stem}_master.mp3")
    loudnorm_2pass = (
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        ":linear=true:print_format=summary"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", str(src),
        "-af", f"{EQ_FILTERS},{loudnorm_2pass}",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "320k",
        str(out_mp3),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        log.warning(f"Mastering render failed: {result.stderr[-300:]}")
        return src

    log.info(f"Mastered → {out_mp3.name} (target {TARGET_LUFS} LUFS, 320 kbps CBR)")

    out_wav = src.with_name(f"{src.stem}_master.wav")
    wav_result = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-i", str(out_mp3),
         "-acodec", "pcm_s16le", "-ar", "44100", str(out_wav)],
        capture_output=True, text=True, timeout=600,
    )
    if wav_result.returncode == 0:
        log.info(f"WAV mirror → {out_wav.name}")

    return out_mp3
