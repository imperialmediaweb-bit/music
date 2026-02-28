"""Generate music using Meta's MusicGen model via Hugging Face Inference API.

No browser automation, no credits, no login needed — just an API key.
Each generation produces short audio clips (~10-15 seconds) that get
merged by audio_merger.py into a longer track.

Usage:
    python main.py run --platform musicgen
    python main.py run --platform musicgen --songs 4
"""

import subprocess
import time
from pathlib import Path

import requests

from config import INPUT_DIR, HF_API_KEY
from modules.concept_generator import MusicConcept
from utils.logger import log


# Hugging Face Inference API endpoint
HF_API_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

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
                # Model is loading (cold start)
                try:
                    info = response.json()
                    wait_time = min(info.get("estimated_time", HF_RETRY_DELAY), 120)
                except Exception:
                    wait_time = HF_RETRY_DELAY
                log.info(f"  Model loading, waiting {wait_time:.0f}s...")
                time.sleep(wait_time)
                continue

            elif response.status_code == 429:
                # Rate limited
                log.warning(f"  Rate limited, waiting {HF_RETRY_DELAY}s...")
                time.sleep(HF_RETRY_DELAY)
                continue

            elif response.status_code == 200:
                # Success — save raw audio then convert to MP3
                content_type = response.headers.get("content-type", "")
                log.info(f"  Got audio response ({len(response.content)} bytes, {content_type})")

                # Determine file extension from content type
                if "flac" in content_type:
                    ext = ".flac"
                elif "wav" in content_type:
                    ext = ".wav"
                elif "ogg" in content_type:
                    ext = ".ogg"
                else:
                    ext = ".flac"  # default assumption

                raw_path = output_dir / f"{safe_name}_musicgen_{clip_index}{ext}"
                raw_path.write_bytes(response.content)

                mp3_path = output_dir / f"{safe_name}_musicgen_{clip_index}.mp3"
                _convert_to_mp3(raw_path, mp3_path)
                raw_path.unlink(missing_ok=True)  # clean up temp file

                if _validate_mp3(mp3_path):
                    return mp3_path
                else:
                    log.warning(f"  Generated file failed MP3 validation: {mp3_path.name}")
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


def generate_music_batch(concept: MusicConcept, count: int = 1) -> list[Path]:
    """Generate music using Meta's MusicGen via Hugging Face API.

    Each 'generation' produces 2 audio clips (matching other generators' convention).

    Args:
        concept: The music concept with the prompt.
        count: Number of generations (each = 2 clips).

    Returns:
        List of generated MP3 file paths.
    """
    total_clips = count * 2
    log.info(f"Generating {total_clips} clips via MusicGen for: {concept.track_name}")
    log.info(f"Prompt: {concept.music_prompt or concept.description}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    download_dir = INPUT_DIR / "musicgen_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    prompt = concept.music_prompt or concept.description
    all_mp3s = []

    for i in range(total_clips):
        log.info(f"--- MusicGen clip {i + 1}/{total_clips} ---")

        mp3_path = _generate_clip(prompt, i, download_dir, safe_name)
        if mp3_path:
            all_mp3s.append(mp3_path)
            log.info(f"  Generated: {mp3_path.name} ({mp3_path.stat().st_size / 1024:.0f} KB)")
        else:
            log.warning(f"  Clip {i + 1} failed")

    if not all_mp3s:
        raise RuntimeError(
            "No audio files generated by MusicGen. "
            "Check your HF_API_KEY in .env (get free key: https://huggingface.co/settings/tokens)"
        )

    log.info(f"MusicGen: generated {len(all_mp3s)} MP3 files total")
    return all_mp3s
