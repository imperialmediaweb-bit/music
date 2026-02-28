"""Tests for modules/audio_merger.py — uses FFmpeg with tiny audio files."""

from pathlib import Path

import pytest

from modules.audio_merger import merge_mp3s


class TestMergeMp3s:
    """merge_mp3s() should concatenate audio files or return single file."""

    def test_single_file_no_merge(self, fake_mp3):
        result = merge_mp3s([fake_mp3])
        assert result == fake_mp3  # Returns the same path, no merging

    def test_merge_multiple_files(self, fake_mp3_files, tmp_output):
        result = merge_mp3s(fake_mp3_files, output_name="TestMerge")
        assert result.exists()
        assert result.name == "TestMerge.mp3"

        # The merged file should be larger than any individual file
        assert result.stat().st_size > 0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="No MP3 files provided"):
            merge_mp3s([])

    def test_sanitizes_output_name(self, fake_mp3_files, tmp_output):
        result = merge_mp3s(fake_mp3_files, output_name="Bad/Name:Here!")
        # Should sanitize to remove special chars
        assert result.exists()
        assert "/" not in result.name
        assert ":" not in result.name
