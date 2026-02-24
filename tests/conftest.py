"""Shared fixtures for the music pipeline test suite.

Provides fake MP3 files, PNG images, and MusicConcept instances
so every test can run without hitting external APIs or consuming credits.
"""

import json
import struct
import wave
from pathlib import Path

import pytest
from PIL import Image

from modules.concept_generator import MusicConcept


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 44100) -> bytes:
    """Generate a minimal WAV file in memory (silence)."""
    import io
    n_frames = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_output(tmp_path, monkeypatch):
    """Redirect OUTPUT_DIR to a temp directory so tests don't pollute real output."""
    import config
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def fake_concept() -> MusicConcept:
    """A deterministic MusicConcept for testing."""
    return MusicConcept(
        track_name="Zanu",
        genre="Afro House",
        mood="ritualistic, primal, powerful",
        description="A deep, hypnotic Afro House track.",
        music_prompt="122 BPM Afro House with tribal percussion and deep bass.",
        hashtags=["afrohouse", "tribalbass", "deephouse", "carbass", "music"],
        thumbnail_prompt="A dramatic African tribal mask on dark background.",
        youtube_title="Experience Zanu | Epic Afro House Beats",
        youtube_description="Zanu - A deep Afro House track with heavy bass.",
        youtube_tags=["afro house", "deep house", "tribal", "car bass"],
        tiktok_caption="Zanu #afrohouse #tribal #deepbass",
    )


@pytest.fixture()
def fake_mp3(tmp_path) -> Path:
    """Create a tiny but valid MP3 file (actually WAV renamed — moviepy accepts it)."""
    # moviepy's AudioFileClip can read WAV too, so a real WAV is fine for testing.
    wav_path = tmp_path / "test_track.wav"
    wav_path.write_bytes(_make_wav_bytes(duration_sec=2.0))
    return wav_path


@pytest.fixture()
def fake_mp3_files(tmp_path) -> list[Path]:
    """Create 3 tiny WAV files for merge testing."""
    paths = []
    for i in range(3):
        p = tmp_path / f"track_{i}.wav"
        p.write_bytes(_make_wav_bytes(duration_sec=1.0))
        paths.append(p)
    return paths


@pytest.fixture()
def fake_thumbnail(tmp_path) -> Path:
    """Create a small 1920x1080 PNG thumbnail."""
    img = Image.new("RGB", (1920, 1080), color=(30, 30, 30))
    path = tmp_path / "test_thumbnail.png"
    img.save(str(path), "PNG")
    return path


@pytest.fixture()
def fake_video(tmp_path) -> Path:
    """Create a dummy MP4 file (just a placeholder path for upload tests)."""
    path = tmp_path / "test_video.mp4"
    path.write_bytes(b"\x00" * 1024)  # dummy bytes
    return path


@pytest.fixture()
def openai_concept_response():
    """Canned OpenAI response for concept generation."""
    return {
        "track_name": "Mbawu",
        "mood": "transcendent, powerful",
        "description": "A deep journey through tribal rhythms and heavy bass.",
        "music_prompt": "122 BPM Afro House with congas, djembe, and massive sub-bass.",
        "hashtags": ["afrohouse", "tribalbass", "deephouse", "carbass", "festival"],
        "youtube_title": "Experience Mbawu \ud83c\udf0d | Epic Afro House Beats",
        "youtube_description": "Mbawu - A transcendent Afro House experience.",
        "youtube_tags": ["afro house", "deep house", "tribal", "car bass"],
        "tiktok_caption": "Mbawu #afrohouse #deepbass #tribal",
    }
