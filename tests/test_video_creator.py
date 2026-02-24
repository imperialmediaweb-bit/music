"""Tests for modules/video_creator.py — uses real moviepy with tiny files."""

from pathlib import Path

import pytest
from moviepy import AudioFileClip

from modules.video_creator import create_videos, _resolve_font, _FONT


class TestResolveFont:
    """_resolve_font() should find an available system font."""

    def test_font_is_resolved(self):
        assert _FONT is not None
        assert isinstance(_FONT, str)
        assert len(_FONT) > 0

    def test_resolve_returns_string(self):
        result = _resolve_font()
        assert isinstance(result, str)


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
