"""Merge multiple MP3 files into one with pauses between them."""

from pathlib import Path
from moviepy import AudioFileClip, concatenate_audioclips, AudioClip
from config import OUTPUT_DIR
from utils.logger import log

# Seconds of silence between each track
PAUSE_SECONDS = 2.0


def _make_silence(duration: float, fps: int = 44100) -> AudioClip:
    """Create a silent audio clip of the given duration."""
    return AudioClip(lambda t: [0, 0], duration=duration, fps=fps)


def merge_mp3s(mp3_files: list[Path], output_name: str = "merged") -> Path:
    """Merge multiple MP3 files into one, with pauses between them.

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
        return mp3_files[0]

    log.info(f"Merging {len(mp3_files)} MP3 files with {PAUSE_SECONDS}s pause between each...")

    clips = []
    silence = _make_silence(PAUSE_SECONDS)

    for i, mp3_path in enumerate(mp3_files):
        log.info(f"  Loading [{i + 1}/{len(mp3_files)}]: {mp3_path.name}")
        clip = AudioFileClip(str(mp3_path))
        clips.append(clip)
        # Add silence between tracks (not after the last one)
        if i < len(mp3_files) - 1:
            clips.append(silence)

    # Concatenate all clips
    merged = concatenate_audioclips(clips)
    total_duration = merged.duration
    mins = int(total_duration) // 60
    secs = int(total_duration) % 60
    log.info(f"Merged duration: {mins}:{secs:02d} ({total_duration:.1f} seconds)")

    # Export
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in output_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50] or "merged"
    output_path = OUTPUT_DIR / f"{safe_name}.mp3"

    log.info(f"Exporting merged audio to: {output_path}")
    merged.write_audiofile(str(output_path), logger=None)

    # Clean up
    for clip in clips:
        clip.close()
    merged.close()

    log.info(f"Merged MP3 saved: {output_path}")
    return output_path
