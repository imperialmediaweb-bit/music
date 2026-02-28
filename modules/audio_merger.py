"""Merge multiple MP3 files into one continuous track using FFmpeg."""

import subprocess
import shutil
import tempfile
from pathlib import Path

from config import OUTPUT_DIR
from utils.logger import log


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
        return mp3_files[0]

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
                "-c", "copy",
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

        log.info(f"Merged MP3 saved: {output_path}")
        return output_path

    finally:
        concat_file.unlink(missing_ok=True)
