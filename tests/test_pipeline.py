"""End-to-end tests for the full music pipeline — all external APIs mocked.

These tests verify the entire flow:
  concept → thumbnail → video → YouTube upload → TikTok upload
without consuming any credits or hitting real APIs.
"""

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from modules.concept_generator import MusicConcept
from pipeline import process_single_track, _format_duration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_thumbnail_generator(tmp_output):
    """Return a patch that creates a real PNG instead of calling DALL-E."""
    def fake_generate_thumbnail(prompt, track_name):
        img = Image.new("RGB", (1920, 1080), color=(80, 40, 40))
        safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in track_name)
        safe = safe.strip().replace(" ", "_")[:50]
        path = tmp_output / f"{safe}_thumbnail.png"
        img.save(str(path), "PNG")
        return path
    return patch("pipeline.generate_thumbnail", side_effect=fake_generate_thumbnail)


def _mock_youtube_uploader():
    """Return a patch that fakes a successful YouTube upload."""
    return patch(
        "pipeline.upload_to_youtube",
        return_value="https://youtu.be/test123",
    )


def _mock_tiktok_uploader():
    """Return a patch that fakes a successful TikTok upload."""
    return patch(
        "pipeline.upload_to_tiktok",
        return_value="https://www.tiktok.com/@user/video/456",
    )


def _mock_concept_generator(concept):
    """Return a patch that returns a fixed concept."""
    return patch("pipeline.generate_concept", return_value=concept)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_zero(self):
        assert _format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert _format_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2:05"

    def test_large_duration(self):
        assert _format_duration(893.2) == "14:53"


# ---------------------------------------------------------------------------
# Full pipeline E2E
# ---------------------------------------------------------------------------

class TestProcessSingleTrackE2E:
    """Full end-to-end test: MP3 → concept → thumbnail → video → upload."""

    def test_full_pipeline_success(self, fake_mp3, fake_concept, tmp_output):
        with _mock_thumbnail_generator(tmp_output), \
             _mock_youtube_uploader(), \
             _mock_tiktok_uploader():
            result = process_single_track(fake_mp3, concept=fake_concept)

        assert result["errors"] == [], f"Pipeline had errors: {result['errors']}"
        assert result["concept"] == "Zanu"
        assert result["duration"] is not None
        assert result["thumbnail_path"] is not None
        assert result["youtube_video_path"] is not None
        assert result["tiktok_video_path"] is not None
        assert result["youtube_url"] == "https://youtu.be/test123"
        assert result["tiktok_url"] == "https://www.tiktok.com/@user/video/456"

        # Verify real files were created
        assert Path(result["thumbnail_path"]).exists()
        assert Path(result["youtube_video_path"]).exists()
        assert Path(result["tiktok_video_path"]).exists()

    def test_pipeline_generates_concept_if_not_provided(self, fake_mp3, fake_concept, tmp_output):
        with _mock_concept_generator(fake_concept), \
             _mock_thumbnail_generator(tmp_output), \
             _mock_youtube_uploader(), \
             _mock_tiktok_uploader():
            result = process_single_track(fake_mp3, concept=None)

        assert result["concept"] == "Zanu"
        assert result["errors"] == []

    def test_pipeline_continues_after_youtube_failure(self, fake_mp3, fake_concept, tmp_output):
        with _mock_thumbnail_generator(tmp_output), \
             patch("pipeline.upload_to_youtube", side_effect=Exception("YouTube auth failed")), \
             _mock_tiktok_uploader():
            result = process_single_track(fake_mp3, concept=fake_concept)

        # YouTube failed but TikTok should still succeed
        assert any("youtube" in e for e in result["errors"])
        assert result["tiktok_url"] == "https://www.tiktok.com/@user/video/456"

    def test_pipeline_continues_after_tiktok_failure(self, fake_mp3, fake_concept, tmp_output):
        with _mock_thumbnail_generator(tmp_output), \
             _mock_youtube_uploader(), \
             patch("pipeline.upload_to_tiktok", side_effect=Exception("TikTok not logged in")):
            result = process_single_track(fake_mp3, concept=fake_concept)

        assert result["youtube_url"] == "https://youtu.be/test123"
        assert any("tiktok" in e for e in result["errors"])

    def test_pipeline_stops_if_thumbnail_fails(self, fake_mp3, fake_concept, tmp_output):
        with patch("pipeline.generate_thumbnail", side_effect=Exception("DALL-E quota exceeded")):
            result = process_single_track(fake_mp3, concept=fake_concept)

        assert any("thumbnail" in e for e in result["errors"])
        # Video creation should not have happened
        assert result["youtube_video_path"] is None
        assert result["tiktok_video_path"] is None

    def test_pipeline_stops_if_video_fails(self, fake_mp3, fake_concept, tmp_output):
        with _mock_thumbnail_generator(tmp_output), \
             patch("pipeline.create_videos", side_effect=Exception("Font missing")):
            result = process_single_track(fake_mp3, concept=fake_concept)

        assert any("video" in e for e in result["errors"])
        assert result["youtube_url"] is None
        assert result["tiktok_url"] is None

    def test_pipeline_appends_duration_to_description(self, fake_mp3, fake_concept, tmp_output):
        with _mock_thumbnail_generator(tmp_output), \
             _mock_youtube_uploader(), \
             _mock_tiktok_uploader():
            result = process_single_track(fake_mp3, concept=fake_concept)

        assert "Duration:" in fake_concept.youtube_description

    def test_pipeline_result_structure(self, fake_mp3, fake_concept, tmp_output):
        """Verify the result dict has all expected keys."""
        with _mock_thumbnail_generator(tmp_output), \
             _mock_youtube_uploader(), \
             _mock_tiktok_uploader():
            result = process_single_track(fake_mp3, concept=fake_concept)

        expected_keys = {
            "file", "concept", "duration", "thumbnail_path",
            "youtube_video_path", "tiktok_video_path",
            "youtube_url", "tiktok_url", "errors",
        }
        assert set(result.keys()) == expected_keys


class TestProcessSingleTrackWithMerge:
    """Test the process command flow: merge MP3s → process."""

    def test_merge_then_process(self, fake_mp3_files, fake_concept, tmp_output):
        from modules.audio_merger import merge_mp3s

        merged = merge_mp3s(fake_mp3_files, output_name="MergeE2E")
        assert merged.exists()

        with _mock_thumbnail_generator(tmp_output), \
             _mock_youtube_uploader(), \
             _mock_tiktok_uploader():
            result = process_single_track(merged, concept=fake_concept)

        assert result["errors"] == []
        assert result["youtube_url"] == "https://youtu.be/test123"
