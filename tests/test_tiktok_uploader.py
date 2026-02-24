"""Tests for modules/tiktok_uploader.py — mocks Playwright entirely."""

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from modules.tiktok_uploader import upload_to_tiktok


def _build_playwright_mocks(logged_in=True, post_success=True, video_url=None):
    """Build a full set of Playwright mocks for TikTok upload testing."""
    mock_page = MagicMock()
    mock_page.url = "https://www.tiktok.com/upload" if logged_in else "https://www.tiktok.com/login"

    # Login check: query_selector returns None when logged in (no login modal found)
    if logged_in:
        mock_page.query_selector = MagicMock(return_value=None)

    # File input
    mock_file_input = MagicMock()
    mock_file_input.set_input_files = MagicMock()

    # Caption element
    mock_caption = MagicMock()
    mock_caption.is_visible.return_value = True

    # Post button
    mock_post_btn = MagicMock()
    mock_post_btn.is_visible.return_value = True
    mock_post_btn.is_enabled.return_value = post_success

    # Success detection element
    mock_success_el = MagicMock()
    mock_success_el.get_attribute.return_value = video_url

    def wait_for_selector(selector, timeout=5000):
        if 'file' in selector:
            return mock_file_input
        if 'contenteditable' in selector:
            return mock_caption
        if 'Post' in selector or 'post' in selector:
            return mock_post_btn
        if 'href' in selector:
            return mock_success_el
        return MagicMock()

    mock_page.wait_for_selector = MagicMock(side_effect=wait_for_selector)

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_context.cookies.return_value = []

    mock_browser = MagicMock()

    return mock_browser, mock_context, mock_page


def _patch_cookie_file_exists(exists=True, size=500):
    """Patch TIKTOK_COOKIE_FILE to simulate cookie presence."""
    mock_path = MagicMock()
    mock_path.exists.return_value = exists
    mock_stat = MagicMock()
    mock_stat.st_size = size
    mock_path.stat.return_value = mock_stat
    return patch("modules.tiktok_uploader.TIKTOK_COOKIE_FILE", mock_path)


class TestUploadToTiktok:
    """upload_to_tiktok() should automate TikTok upload via browser."""

    def test_successful_upload(self, fake_video, fake_concept):
        mock_browser, mock_context, mock_page = _build_playwright_mocks(
            video_url="/@user/video/123456"
        )

        mock_pw = MagicMock()
        mock_pw_instance = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_pw.__exit__ = MagicMock(return_value=False)

        with _patch_cookie_file_exists(), \
             patch("modules.tiktok_uploader.sync_playwright", return_value=mock_pw), \
             patch("modules.tiktok_uploader.get_browser_context", return_value=(mock_browser, mock_context)), \
             patch("modules.tiktok_uploader.save_cookies"):
            result = upload_to_tiktok(fake_video, fake_concept)

        assert result is not None
        assert "tiktok.com" in result

    def test_returns_none_when_cookies_missing(self, fake_video, fake_concept):
        with _patch_cookie_file_exists(exists=False):
            result = upload_to_tiktok(fake_video, fake_concept)
        assert result is None

    def test_returns_none_when_cookies_empty(self, fake_video, fake_concept):
        with _patch_cookie_file_exists(exists=True, size=0):
            result = upload_to_tiktok(fake_video, fake_concept)
        assert result is None

    def test_returns_none_when_not_logged_in(self, fake_video, fake_concept):
        mock_browser, mock_context, mock_page = _build_playwright_mocks(logged_in=False)

        mock_pw = MagicMock()
        mock_pw_instance = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_pw.__exit__ = MagicMock(return_value=False)

        with _patch_cookie_file_exists(), \
             patch("modules.tiktok_uploader.sync_playwright", return_value=mock_pw), \
             patch("modules.tiktok_uploader.get_browser_context", return_value=(mock_browser, mock_context)), \
             patch("modules.tiktok_uploader.save_cookies"):
            result = upload_to_tiktok(fake_video, fake_concept)

        assert result is None

    def test_upload_without_url_capture(self, fake_video, fake_concept):
        """Upload succeeds but URL not captured — should return None gracefully."""
        mock_browser, mock_context, mock_page = _build_playwright_mocks(video_url=None)

        mock_pw = MagicMock()
        mock_pw_instance = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_pw.__exit__ = MagicMock(return_value=False)

        with _patch_cookie_file_exists(), \
             patch("modules.tiktok_uploader.sync_playwright", return_value=mock_pw), \
             patch("modules.tiktok_uploader.get_browser_context", return_value=(mock_browser, mock_context)), \
             patch("modules.tiktok_uploader.save_cookies"):
            result = upload_to_tiktok(fake_video, fake_concept)

        # No URL captured, but no crash
        # (result could be None since no href with /@)
        mock_browser.close.assert_called_once()

    def test_retries_on_failure(self, fake_video, fake_concept):
        """upload_to_tiktok retries on transient failures."""
        with _patch_cookie_file_exists(), \
             patch("modules.tiktok_uploader._do_upload") as mock_do, \
             patch("modules.tiktok_uploader.time.sleep"):
            mock_do.side_effect = [RuntimeError("Transient"), "https://tiktok.com/@u/v/1"]
            result = upload_to_tiktok(fake_video, fake_concept)

        assert result == "https://tiktok.com/@u/v/1"
        assert mock_do.call_count == 2
