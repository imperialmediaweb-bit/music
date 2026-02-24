"""Tests for modules/thumbnail_generator.py — mocks DALL-E 3 API entirely."""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from modules.thumbnail_generator import generate_thumbnail, _add_track_name


class TestAddTrackName:
    """_add_track_name() overlays text on an image."""

    def test_returns_image_with_text(self):
        img = Image.new("RGB", (1792, 1024), color=(50, 50, 50))
        result = _add_track_name(img, "ZANU")
        assert isinstance(result, Image.Image)
        assert result.size == (1792, 1024)

    def test_handles_long_names(self):
        img = Image.new("RGB", (1792, 1024), color=(50, 50, 50))
        result = _add_track_name(img, "A" * 100)
        assert isinstance(result, Image.Image)

    def test_handles_empty_name(self):
        img = Image.new("RGB", (1792, 1024), color=(50, 50, 50))
        result = _add_track_name(img, "")
        assert isinstance(result, Image.Image)


class TestGenerateThumbnail:
    """generate_thumbnail() should call DALL-E and save a PNG."""

    def _mock_dalle(self, openai_mock):
        """Set up DALL-E mock to return a valid image URL."""
        # Create a small test image in memory
        img = Image.new("RGB", (1792, 1024), color=(100, 50, 50))
        buf = BytesIO()
        img.save(buf, "PNG")
        image_bytes = buf.getvalue()

        mock_data = MagicMock()
        mock_data.url = "https://fake-dalle.example.com/image.png"
        mock_response = MagicMock()
        mock_response.data = [mock_data]

        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response
        openai_mock.return_value = mock_client

        return image_bytes

    def test_generates_and_saves_thumbnail(self, tmp_output):
        with patch("modules.thumbnail_generator.OpenAI") as mock_openai, \
             patch("modules.thumbnail_generator.requests.get") as mock_get:

            image_bytes = self._mock_dalle(mock_openai)

            mock_resp = MagicMock()
            mock_resp.content = image_bytes
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = generate_thumbnail("African mask prompt", "Zanu")

        assert result.exists()
        assert result.suffix == ".png"
        assert "Zanu" in result.name

        # Verify it's a valid image
        img = Image.open(result)
        assert img.size == (1792, 1024)

    def test_retries_on_api_error(self, tmp_output):
        with patch("modules.thumbnail_generator.OpenAI") as mock_openai, \
             patch("modules.thumbnail_generator.requests.get") as mock_get, \
             patch("modules.thumbnail_generator.time.sleep"):

            # Create the image for the successful response
            img = Image.new("RGB", (1792, 1024), color=(100, 50, 50))
            buf = BytesIO()
            img.save(buf, "PNG")
            image_bytes = buf.getvalue()

            mock_data = MagicMock()
            mock_data.url = "https://fake.example.com/image.png"
            mock_response = MagicMock()
            mock_response.data = [mock_data]

            mock_client = MagicMock()
            mock_client.images.generate.side_effect = [
                ConnectionError("timeout"),
                mock_response,
            ]
            mock_openai.return_value = mock_client

            mock_resp = MagicMock()
            mock_resp.content = image_bytes
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result = generate_thumbnail("prompt", "RetryTest")
            assert result.exists()

    def test_raises_after_4_failures(self, tmp_output):
        with patch("modules.thumbnail_generator.OpenAI") as mock_openai, \
             patch("modules.thumbnail_generator.time.sleep"):
            mock_client = MagicMock()
            mock_client.images.generate.side_effect = ConnectionError("timeout")
            mock_openai.return_value = mock_client

            with pytest.raises(RuntimeError, match="DALL-E API failed after 4 attempts"):
                generate_thumbnail("prompt", "FailTest")
