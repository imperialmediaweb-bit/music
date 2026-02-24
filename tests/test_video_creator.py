"""Tests for modules/video_creator.py — uses FFmpeg with tiny files."""

import shutil
from pathlib import Path

import pytest

from modules.video_creator import create_videos


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
class TestCreateVideos:
    """create_videos() should produce YouTube and TikTok MP4 files."""

    def test_creates_both_videos(self, fake_mp3, fake_thumbnail, fake_concept, tmp_output):
        yt_path, tk_path = create_videos(fake_mp3, fake_thumbnail, fake_concept)

        assert yt_path.exists(), "YouTube video not created"
        assert tk_path.exists(), "TikTok video not created"
        assert yt_path.suffix == ".mp4"
        assert tk_path.suffix == ".mp4"
        assert yt_path.stat().st_size > 0
        assert tk_path.stat().st_size > 0

    def test_video_filenames_contain_track_name(self, fake_mp3, fake_thumbnail, fake_concept, tmp_output):
        yt_path, tk_path = create_videos(fake_mp3, fake_thumbnail, fake_concept)

        assert "Zanu" in yt_path.name
        assert "youtube" in yt_path.name
        assert "Zanu" in tk_path.name
        assert "tiktok" in tk_path.name

    def test_sanitizes_track_name_in_filename(self, fake_mp3, fake_thumbnail, fake_concept, tmp_output):
        fake_concept.track_name = "Bad/Name:Here!"
        yt_path, tk_path = create_videos(fake_mp3, fake_thumbnail, fake_concept)

        assert yt_path.exists()
        assert "/" not in yt_path.name
        assert ":" not in yt_path.name
