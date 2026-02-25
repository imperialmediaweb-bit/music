"""Tests for modules/youtube_uploader.py — mocks YouTube API entirely."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.youtube_uploader import (
    upload_to_youtube,
    _get_authenticated_service,
    _find_or_create_playlist,
    _add_to_playlist,
    SCOPES,
)


class TestGetAuthenticatedService:
    """_get_authenticated_service() handles OAuth flow."""

    def test_loads_existing_valid_token(self):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.scopes = set(SCOPES)

        with patch("modules.youtube_uploader.TOKEN_FILE") as mock_tf, \
             patch("modules.youtube_uploader.pickle") as mock_pickle, \
             patch("modules.youtube_uploader.build") as mock_build, \
             patch("builtins.open", MagicMock()):
            mock_tf.exists.return_value = True
            mock_pickle.load.return_value = mock_creds

            _get_authenticated_service()

        mock_build.assert_called_once_with("youtube", "v3", credentials=mock_creds)

    def test_refreshes_expired_token(self):
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "fake-refresh"
        mock_creds.scopes = set(SCOPES)

        # After refresh(), valid should become True
        def make_valid(*args):
            mock_creds.valid = True
        mock_creds.refresh.side_effect = make_valid

        with patch("modules.youtube_uploader.TOKEN_FILE") as mock_tf, \
             patch("modules.youtube_uploader.pickle") as mock_pickle, \
             patch("modules.youtube_uploader.build") as mock_build, \
             patch("modules.youtube_uploader.Request") as mock_request, \
             patch("builtins.open", MagicMock()):
            mock_tf.exists.return_value = True
            mock_pickle.load.return_value = mock_creds

            _get_authenticated_service()

        mock_creds.refresh.assert_called_once()
        mock_build.assert_called_once()

    def test_raises_if_no_client_secrets(self):
        with patch("modules.youtube_uploader.TOKEN_FILE") as mock_tf, \
             patch("modules.youtube_uploader.CLIENT_SECRETS_FILE") as mock_sf:
            mock_tf.exists.return_value = False
            mock_sf.exists.return_value = False

            with pytest.raises(FileNotFoundError, match="OAuth client secrets not found"):
                _get_authenticated_service()


class TestUploadToYoutube:
    """upload_to_youtube() should upload video and thumbnail."""

    def test_successful_upload(self, fake_video, fake_thumbnail, fake_concept):
        mock_youtube = MagicMock()

        mock_insert_request = MagicMock()
        mock_insert_request.next_chunk.return_value = (None, {"id": "abc123"})
        mock_youtube.videos.return_value.insert.return_value = mock_insert_request

        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}

        with patch("modules.youtube_uploader._get_authenticated_service", return_value=mock_youtube), \
             patch("modules.youtube_uploader.MediaFileUpload"):
            result = upload_to_youtube(fake_video, fake_thumbnail, fake_concept)

        assert result == "https://youtu.be/abc123"

    def test_upload_with_chunked_progress(self, fake_video, fake_thumbnail, fake_concept):
        mock_youtube = MagicMock()

        mock_status_50 = MagicMock()
        mock_status_50.progress.return_value = 0.5

        mock_insert_request = MagicMock()
        mock_insert_request.next_chunk.side_effect = [
            (mock_status_50, None),
            (None, {"id": "xyz789"}),
        ]
        mock_youtube.videos.return_value.insert.return_value = mock_insert_request
        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}

        with patch("modules.youtube_uploader._get_authenticated_service", return_value=mock_youtube), \
             patch("modules.youtube_uploader.MediaFileUpload"):
            result = upload_to_youtube(fake_video, fake_thumbnail, fake_concept)

        assert result == "https://youtu.be/xyz789"

    def test_returns_none_if_no_secrets(self, fake_video, fake_thumbnail, fake_concept):
        with patch(
            "modules.youtube_uploader._get_authenticated_service",
            side_effect=FileNotFoundError("OAuth client secrets not found"),
        ):
            result = upload_to_youtube(fake_video, fake_thumbnail, fake_concept)
        assert result is None

    def test_thumbnail_failure_not_fatal(self, fake_video, fake_thumbnail, fake_concept):
        mock_youtube = MagicMock()
        mock_insert_request = MagicMock()
        mock_insert_request.next_chunk.return_value = (None, {"id": "thumb_fail"})
        mock_youtube.videos.return_value.insert.return_value = mock_insert_request

        mock_youtube.thumbnails.return_value.set.return_value.execute.side_effect = \
            Exception("Account not verified")

        with patch("modules.youtube_uploader._get_authenticated_service", return_value=mock_youtube), \
             patch("modules.youtube_uploader.MediaFileUpload"):
            result = upload_to_youtube(fake_video, fake_thumbnail, fake_concept)

        assert result == "https://youtu.be/thumb_fail"

    def test_metadata_limits(self, fake_video, fake_thumbnail, fake_concept):
        fake_concept.youtube_title = "A" * 200
        fake_concept.youtube_description = "B" * 10000
        fake_concept.youtube_tags = [f"tag{i}" for i in range(50)]

        mock_youtube = MagicMock()
        mock_insert_request = MagicMock()
        mock_insert_request.next_chunk.return_value = (None, {"id": "limits_test"})
        mock_youtube.videos.return_value.insert.return_value = mock_insert_request
        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}

        with patch("modules.youtube_uploader._get_authenticated_service", return_value=mock_youtube), \
             patch("modules.youtube_uploader.MediaFileUpload"):
            result = upload_to_youtube(fake_video, fake_thumbnail, fake_concept)

        call_kwargs = mock_youtube.videos.return_value.insert.call_args
        body = call_kwargs[1]["body"]
        assert len(body["snippet"]["title"]) <= 100
        assert len(body["snippet"]["description"]) <= 5000
        assert len(body["snippet"]["tags"]) <= 30
        # Total tag characters (with comma separators) must not exceed 500
        total = sum(len(t) for t in body["snippet"]["tags"]) + max(len(body["snippet"]["tags"]) - 1, 0)
        assert total <= 500
        assert result == "https://youtu.be/limits_test"

    def test_tags_sanitized(self, fake_video, fake_thumbnail, fake_concept):
        """Tags with <, >, or # prefix should be cleaned before upload."""
        fake_concept.youtube_tags = ["#afrohouse", "deep <house>", "tribal", ""]

        mock_youtube = MagicMock()
        mock_insert_request = MagicMock()
        mock_insert_request.next_chunk.return_value = (None, {"id": "sanitize_test"})
        mock_youtube.videos.return_value.insert.return_value = mock_insert_request
        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}

        with patch("modules.youtube_uploader._get_authenticated_service", return_value=mock_youtube), \
             patch("modules.youtube_uploader.MediaFileUpload"):
            upload_to_youtube(fake_video, fake_thumbnail, fake_concept)

        call_kwargs = mock_youtube.videos.return_value.insert.call_args
        tags = call_kwargs[1]["body"]["snippet"]["tags"]
        for tag in tags:
            assert "<" not in tag and ">" not in tag
            assert not tag.startswith("#")
        assert "" not in tags

    def test_playlist_failure_not_fatal(self, fake_video, fake_thumbnail, fake_concept):
        """Playlist add failure should not prevent upload from succeeding."""
        mock_youtube = MagicMock()
        mock_insert_request = MagicMock()
        mock_insert_request.next_chunk.return_value = (None, {"id": "pl_fail"})
        mock_youtube.videos.return_value.insert.return_value = mock_insert_request
        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}
        # Playlist call raises
        mock_youtube.playlists.return_value.list.return_value.execute.side_effect = \
            Exception("Playlist API error")

        with patch("modules.youtube_uploader._get_authenticated_service", return_value=mock_youtube), \
             patch("modules.youtube_uploader.MediaFileUpload"):
            result = upload_to_youtube(fake_video, fake_thumbnail, fake_concept)

        assert result == "https://youtu.be/pl_fail"


class TestScopeMismatchDetection:
    """Scope mismatch should force re-authentication."""

    def test_deletes_token_on_scope_mismatch(self):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.scopes = {"https://www.googleapis.com/auth/youtube.upload"}

        with patch("modules.youtube_uploader.TOKEN_FILE") as mock_tf, \
             patch("modules.youtube_uploader.CLIENT_SECRETS_FILE") as mock_sf, \
             patch("modules.youtube_uploader.pickle") as mock_pickle, \
             patch("modules.youtube_uploader.build") as mock_build, \
             patch("modules.youtube_uploader.InstalledAppFlow") as mock_flow, \
             patch("builtins.open", MagicMock()):
            mock_tf.exists.return_value = True
            mock_pickle.load.return_value = mock_creds
            mock_sf.exists.return_value = True

            new_creds = MagicMock()
            new_creds.valid = True
            mock_flow.from_client_secrets_file.return_value.run_local_server.return_value = new_creds

            _get_authenticated_service()

        # Old token should be deleted
        mock_tf.unlink.assert_called_once_with(missing_ok=True)
        # New OAuth flow should be triggered
        mock_flow.from_client_secrets_file.assert_called_once()

    def test_keeps_token_when_scopes_match(self):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.scopes = set(SCOPES)

        with patch("modules.youtube_uploader.TOKEN_FILE") as mock_tf, \
             patch("modules.youtube_uploader.pickle") as mock_pickle, \
             patch("modules.youtube_uploader.build") as mock_build, \
             patch("builtins.open", MagicMock()):
            mock_tf.exists.return_value = True
            mock_pickle.load.return_value = mock_creds

            _get_authenticated_service()

        mock_tf.unlink.assert_not_called()
        mock_build.assert_called_once_with("youtube", "v3", credentials=mock_creds)


class TestFindOrCreatePlaylist:
    """_find_or_create_playlist() should find or create an Afro House playlist."""

    def test_finds_existing_playlist(self):
        mock_youtube = MagicMock()
        mock_youtube.playlists.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "PL123", "snippet": {"title": "Afro House"}},
            ]
        }

        result = _find_or_create_playlist(mock_youtube, "Afro House")
        assert result == "PL123"
        mock_youtube.playlists.return_value.insert.assert_not_called()

    def test_creates_playlist_if_not_found(self):
        mock_youtube = MagicMock()
        mock_youtube.playlists.return_value.list.return_value.execute.return_value = {
            "items": []
        }
        mock_youtube.playlists.return_value.insert.return_value.execute.return_value = {
            "id": "PL_NEW"
        }

        result = _find_or_create_playlist(mock_youtube, "Afro House")
        assert result == "PL_NEW"
        mock_youtube.playlists.return_value.insert.assert_called_once()

    def test_case_insensitive_match(self):
        mock_youtube = MagicMock()
        mock_youtube.playlists.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "PL456", "snippet": {"title": "afro house"}},
            ]
        }

        result = _find_or_create_playlist(mock_youtube, "Afro House")
        assert result == "PL456"


class TestAddToPlaylist:
    """_add_to_playlist() should add a video to a playlist."""

    def test_adds_video(self):
        mock_youtube = MagicMock()
        _add_to_playlist(mock_youtube, "PL123", "vid456")

        call_kwargs = mock_youtube.playlistItems.return_value.insert.call_args
        body = call_kwargs[1]["body"]
        assert body["snippet"]["playlistId"] == "PL123"
        assert body["snippet"]["resourceId"]["videoId"] == "vid456"
