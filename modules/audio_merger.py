"""Merge multiple MP3 files into one continuous track."""

from pathlib import Path
from moviepy import AudioFileClip, concatenate_audioclips
from config import OUTPUT_DIR
from utils.logger import log


def merge_mp3s(mp3_files: list[Path], output_name: str = "merged") -> Path:
    """Merge multiple MP3 files into one continuous track (no gaps).

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
        # Still export WAV for TuneCore distribution
        single = mp3_files[0]
        wav_path = OUTPUT_DIR / f"{single.stem}.wav"
        if not wav_path.exists():
            log.info(f"Exporting WAV for TuneCore: {wav_path}")
            clip = AudioFileClip(str(single))
            clip.write_audiofile(str(wav_path), codec="pcm_s16le", logger=None)
            clip.close()
            log.info(f"WAV saved: {wav_path}")
        return single

    log.info(f"Merging {len(mp3_files)} MP3 files back to back (no gaps)...")

    clips = []
    for i, mp3_path in enumerate(mp3_files):
        log.info(f"  Loading [{i + 1}/{len(mp3_files)}]: {mp3_path.name}")
        clip = AudioFileClip(str(mp3_path))
        clips.append(clip)

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

    # Also export WAV for TuneCore distribution
    wav_path = output_path.with_suffix(".wav")
    log.info(f"Exporting WAV for TuneCore: {wav_path}")
    merged.write_audiofile(str(wav_path), codec="pcm_s16le", logger=None)
    log.info(f"WAV saved: {wav_path}")

    # Clean up
    for clip in clips:
        clip.close()
    merged.close()

    log.info(f"Merged MP3 saved: {output_path}")
    return output_path
