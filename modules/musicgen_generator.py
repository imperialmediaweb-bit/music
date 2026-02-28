"""Generate music using Meta's MusicGen model via Hugging Face Inference API.

No browser automation, no credits, no login needed — just an API key.
Generates many short clips (~12 seconds each), then cross-fades them
together into long, seamless tracks (6+ minutes).

Usage:
    python main.py run --platform musicgen
    python main.py run --platform musicgen --duration 20
"""

import json
import subprocess
import time
from pathlib import Path

import requests

from config import INPUT_DIR, HF_API_KEY
from modules.concept_generator import MusicConcept
from utils.logger import log


# Hugging Face Inference API endpoint
HF_API_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

# Average duration of one MusicGen clip (seconds)
CLIP_DURATION_SEC = 12

# Cross-fade duration between clips (seconds)
CROSSFADE_SEC = 3

# Default target duration per track (minutes)
DEFAULT_DURATION_MIN = 6

# Retry settings (model may need to warm up on first call)
HF_MAX_RETRIES = 5
HF_RETRY_DELAY = 30  # seconds between retries


def _validate_mp3(path: Path) -> bool:
    """Check if a file is a valid MP3."""
    if not path.exists():
        return False
    size = path.stat().st_size
    if size < 10_000:
        log.warning(f"Validation: file too small ({size} bytes): {path.name}")
        return False
    header = path.read_bytes()[:16]
    if header[:3] == b'ID3':
        return True
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True
    return False


def _get_audio_duration(path: Path) -> float:
    """Get duration of an audio file in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _convert_to_mp3(input_path: Path, output_path: Path) -> Path:
    """Convert audio file (FLAC/WAV) to MP3 using ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path),
         "-codec:a", "libmp3lame", "-q:a", "2", str(output_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error(f"ffmpeg conversion failed: {result.stderr[:300]}")
        raise RuntimeError(f"ffmpeg failed to convert {input_path.name} to MP3")
    return output_path


def _generate_clip(prompt: str, clip_index: int,
                   output_dir: Path, safe_name: str) -> Path | None:
    """Generate a single audio clip via HF Inference API."""
    if not HF_API_KEY:
        log.error("HF_API_KEY not set in .env — get a free key at https://huggingface.co/settings/tokens")
        return None

    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {"inputs": prompt}

    for attempt in range(1, HF_MAX_RETRIES + 1):
        try:
            log.info(f"  Calling HF API (attempt {attempt}/{HF_MAX_RETRIES})...")
            response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=180)

            if response.status_code == 503:
                try:
                    info = response.json()
                    wait_time = min(info.get("estimated_time", HF_RETRY_DELAY), 120)
                except Exception:
                    wait_time = HF_RETRY_DELAY
                log.info(f"  Model loading, waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue

            elif response.status_code == 429:
                log.warning(f"  Rate limited, waiting {HF_RETRY_DELAY}s...")
                time.sleep(HF_RETRY_DELAY)
                continue

            elif response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                log.info(f"  Got audio ({len(response.content)} bytes)")

                if "flac" in content_type:
                    ext = ".flac"
                elif "wav" in content_type:
                    ext = ".wav"
                elif "ogg" in content_type:
                    ext = ".ogg"
                else:
                    ext = ".flac"

                raw_path = output_dir / f"{safe_name}_clip_{clip_index}{ext}"
                raw_path.write_bytes(response.content)

                mp3_path = output_dir / f"{safe_name}_clip_{clip_index}.mp3"
                _convert_to_mp3(raw_path, mp3_path)
                raw_path.unlink(missing_ok=True)

                if _validate_mp3(mp3_path):
                    return mp3_path
                else:
                    log.warning(f"  Generated file failed validation: {mp3_path.name}")
                    return None

            else:
                error_text = response.text[:300]
                log.warning(f"  HF API error {response.status_code}: {error_text}")
                if attempt < HF_MAX_RETRIES:
                    time.sleep(HF_RETRY_DELAY)

        except requests.exceptions.Timeout:
            log.warning(f"  Request timed out (attempt {attempt}/{HF_MAX_RETRIES})")
            if attempt < HF_MAX_RETRIES:
                time.sleep(10)
        except requests.exceptions.ConnectionError as e:
            log.warning(f"  Connection error: {e}")
            if attempt < HF_MAX_RETRIES:
                time.sleep(10)

    log.error(f"  Failed to generate clip {clip_index} after {HF_MAX_RETRIES} attempts")
    return None


def _crossfade_merge(clips: list[Path], output_path: Path, crossfade_sec: float = CROSSFADE_SEC) -> Path:
    """Merge multiple short clips into one long track with cross-fade transitions.

    Uses ffmpeg's acrossfade filter to smoothly blend clips together.
    """
    if len(clips) == 1:
        # Just copy the single clip
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(clips[0]),
             "-codec:a", "libmp3lame", "-q:a", "2", str(output_path)],
            capture_output=True, text=True, check=True,
        )
        return output_path

    # For many clips, chain acrossfade filters progressively
    # ffmpeg can handle this by chaining: clip1 + clip2 -> temp1, temp1 + clip3 -> temp2, etc.
    current = clips[0]
    temp_dir = output_path.parent
    temp_files = []

    for i in range(1, len(clips)):
        next_clip = clips[i]
        if i < len(clips) - 1:
            temp_out = temp_dir / f"_crossfade_temp_{i}.mp3"
            temp_files.append(temp_out)
        else:
            temp_out = output_path

        # Use acrossfade filter for smooth transition
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(current),
                "-i", str(next_clip),
                "-filter_complex",
                f"acrossfade=d={crossfade_sec}:c1=tri:c2=tri",
                "-codec:a", "libmp3lame", "-q:a", "2",
                str(temp_out),
            ],
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            log.warning(f"  Cross-fade failed at clip {i}, falling back to simple concat")
            # Fallback: simple concatenation without crossfade
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(current),
                    "-i", str(next_clip),
                    "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                    "-codec:a", "libmp3lame", "-q:a", "2",
                    str(temp_out),
                ],
                capture_output=True, text=True,
            )

        current = temp_out

        if (i % 10 == 0) or (i == len(clips) - 1):
            log.info(f"  Cross-fade progress: {i}/{len(clips) - 1} clips merged")

    # Clean up temp files
    for temp in temp_files:
        temp.unlink(missing_ok=True)

    return output_path


def generate_music_batch(concept: MusicConcept, count: int = 1,
                         duration_min: int = DEFAULT_DURATION_MIN) -> list[Path]:
    """Generate long music tracks using MusicGen with cross-fade merging.

    Generates many short clips (~12 sec each), then cross-fades them together
    into seamless long tracks. Each 'generation' (count) produces one long track.

    Args:
        concept: The music concept with the prompt.
        count: Number of long tracks to produce.
        duration_min: Target duration per track in minutes (default: 6).

    Returns:
        List of generated MP3 file paths (long tracks).
    """
    target_sec = duration_min * 60
    # Each clip is ~12 sec, cross-fade eats ~3 sec per join
    effective_per_clip = CLIP_DURATION_SEC - CROSSFADE_SEC
    clips_needed = max(3, int(target_sec / effective_per_clip) + 2)

    log.info(f"MusicGen: generating {count} track(s), ~{duration_min} min each")
    log.info(f"  Need ~{clips_needed} clips per track ({CLIP_DURATION_SEC}s each, {CROSSFADE_SEC}s cross-fade)")
    log.info(f"  Prompt: {concept.music_prompt or concept.description}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    download_dir = INPUT_DIR / "musicgen_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    prompt = concept.music_prompt or concept.description
    all_tracks = []

    for track_idx in range(count):
        if count > 1:
            log.info(f"\n=== Track {track_idx + 1}/{count} ===")

        # Generate all short clips for this track
        clips = []
        for i in range(clips_needed):
            log.info(f"--- Clip {i + 1}/{clips_needed} (track {track_idx + 1}) ---")
            mp3_path = _generate_clip(prompt, track_idx * 1000 + i, download_dir, safe_name)
            if mp3_path:
                clips.append(mp3_path)
                log.info(f"  OK: {mp3_path.name} ({mp3_path.stat().st_size / 1024:.0f} KB)")
            else:
                log.warning(f"  Clip {i + 1} failed, continuing...")

        if not clips:
            log.error(f"No clips generated for track {track_idx + 1}")
            continue

        log.info(f"\nMerging {len(clips)} clips with cross-fade into one track...")

        # Cross-fade merge all clips into one long track
        track_path = download_dir / f"{safe_name}_track_{track_idx}.mp3"
        _crossfade_merge(clips, track_path)

        if track_path.exists() and _validate_mp3(track_path):
            duration = _get_audio_duration(track_path)
            mins = int(duration) // 60
            secs = int(duration) % 60
            log.info(f"  Track ready: {track_path.name} ({mins}:{secs:02d}, {track_path.stat().st_size / 1024 / 1024:.1f} MB)")
            all_tracks.append(track_path)

            # Clean up individual clips
            for clip in clips:
                clip.unlink(missing_ok=True)
        else:
            log.error(f"  Track merge failed for track {track_idx + 1}")

    if not all_tracks:
        raise RuntimeError(
            "No tracks generated by MusicGen. "
            "Check your HF_API_KEY in .env (get free key: https://huggingface.co/settings/tokens)"
        )

    log.info(f"\nMusicGen: {len(all_tracks)} track(s) ready")
    return all_tracks
