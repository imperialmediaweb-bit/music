"""Tests for modules/video_creator.py — uses FFmpeg with tiny files."""

import shutil
from pathlib import Path

import pytest

from modules.video_creator import create_video


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
class TestCreateVideo:
    """create_video() should produce a single MP4 file."""

    def test_creates_video(self, fake_mp3, fake_thumbnail, fake_concept, tmp_output):
        video_path = create_video(fake_mp3, fake_thumbnail, fake_concept)

        assert video_path.exists(), "Video not created"
        assert video_path.suffix == ".mp4"
        assert video_path.stat().st_size > 0

    def test_video_filename_contains_track_name(self, fake_mp3, fake_thumbnail, fake_concept, tmp_output):
        video_path = create_video(fake_mp3, fake_thumbnail, fake_concept)

        assert "Zanu" in video_path.name
        assert "_video.mp4" in video_path.name

    def test_sanitizes_track_name_in_filename(self, fake_mp3, fake_thumbnail, fake_concept, tmp_output):
        fake_concept.track_name = "Bad/Name:Here!"
        video_path = create_video(fake_mp3, fake_thumbnail, fake_concept)

        assert video_path.exists()
        assert "/" not in video_path.name
        assert ":" not in video_path.name
