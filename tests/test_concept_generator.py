"""Tests for modules/concept_generator.py — mocks OpenAI API entirely."""

import json
from unittest.mock import MagicMock, patch

import pytest

from modules.concept_generator import generate_concept, MusicConcept


class TestGenerateConcept:
    """generate_concept() should call OpenAI and return a MusicConcept."""

    def test_returns_music_concept(self, openai_concept_response):
        mock_message = MagicMock()
        mock_message.content = json.dumps(openai_concept_response)
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("modules.concept_generator.OpenAI", return_value=mock_client):
            concept = generate_concept()

        assert isinstance(concept, MusicConcept)
        assert concept.track_name == "Mbawu"
        assert concept.genre == "Afro House"
        assert concept.mood == "transcendent, powerful"
        assert len(concept.hashtags) >= 5
        assert concept.youtube_title.startswith("Experience Mbawu")
        assert "#afrohouse" in concept.tiktok_caption

    def test_retries_on_api_error(self, openai_concept_response):
        mock_message = MagicMock()
        mock_message.content = json.dumps(openai_concept_response)
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        # Fail twice, succeed on third attempt
        mock_client.chat.completions.create.side_effect = [
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            mock_response,
        ]

        with patch("modules.concept_generator.OpenAI", return_value=mock_client), \
             patch("modules.concept_generator.time.sleep"):
            concept = generate_concept()

        assert concept.track_name == "Mbawu"
        assert mock_client.chat.completions.create.call_count == 3

    def test_raises_after_4_failures(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = ConnectionError("timeout")

        with patch("modules.concept_generator.OpenAI", return_value=mock_client), \
             patch("modules.concept_generator.time.sleep"), \
             pytest.raises(RuntimeError, match="OpenAI API failed after 4 attempts"):
            generate_concept()

    def test_uses_defaults_for_missing_fields(self):
        # Only track_name, rest will use defaults
        mock_message = MagicMock()
        mock_message.content = json.dumps({"track_name": "Tikala"})
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("modules.concept_generator.OpenAI", return_value=mock_client):
            concept = generate_concept()

        assert concept.track_name == "Tikala"
        assert concept.genre == "Afro House"
        assert concept.mood == "ritualistic, primal, powerful, transcendent"
        assert len(concept.hashtags) > 0
        assert concept.thumbnail_prompt  # Should always be set
