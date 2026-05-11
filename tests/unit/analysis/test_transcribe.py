"""Tests for transcription dispatcher and remote engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autoedit.analysis.transcribe import transcribe_audio


class TestTranscribeDispatcher:
    """TC-ANL-001 — provider dispatch logic."""

    @patch("autoedit.analysis.transcribe.transcribe_local")
    def test_local_provider_by_default(self, mock_local: Any, tmp_path: Path) -> None:
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake_audio")
        out = tmp_path / "transcript.json"

        mock_local.return_value = {"language": "es", "duration": 10.0, "segments": []}
        transcribe_audio(str(audio), str(out), language="es")

        mock_local.assert_called_once()
        call_kwargs = mock_local.call_args.kwargs
        assert call_kwargs["audio_path"] == str(audio)
        assert call_kwargs["language"] == "es"

    @patch("autoedit.analysis.transcribe.transcribe_remote")
    def test_remote_provider_when_configured(self, mock_remote: Any, tmp_path: Path) -> None:
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake_audio")
        out = tmp_path / "transcript.json"

        mock_remote.return_value = {"language": "en", "duration": 5.0, "segments": []}
        with patch("autoedit.analysis.transcribe.settings") as mock_settings:
            mock_settings.TRANSCRIPTION_PROVIDER = "remote"
            transcribe_audio(str(audio), str(out), language="en")

        mock_remote.assert_called_once()
        call_kwargs = mock_remote.call_args.kwargs
        assert call_kwargs["audio_path"] == str(audio)
        assert call_kwargs["language"] == "en"


class TestTranscribeRemote:
    """TC-ANL-002 — remote API normalization."""

    @patch("autoedit.analysis.transcribe_remote.httpx.post")
    def test_remote_normalizes_response(self, mock_post: Any, tmp_path: Path) -> None:
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"fake_audio")

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "language": "es",
                "duration": 12.0,
                "segments": [
                    {
                        "id": 0,
                        "start": 0.0,
                        "end": 12.0,
                        "text": "Hola mundo",
                        "words": [
                            {"word": "Hola", "start": 0.0, "end": 0.5},
                            {"word": "mundo", "start": 0.5, "end": 1.0},
                        ],
                    }
                ],
            },
        )

        with patch("autoedit.analysis.transcribe_remote.settings") as mock_settings:
            mock_settings.TRANSCRIPTION_REMOTE_BASE_URL = "https://api.example.com/v1"
            mock_settings.TRANSCRIPTION_REMOTE_API_KEY = "sk-test"
            mock_settings.TRANSCRIPTION_REMOTE_MODEL = "whisper-1"
            mock_settings.OPENROUTER_API_KEY = ""

            from autoedit.analysis.transcribe_remote import transcribe_remote

            result = transcribe_remote(str(audio), language="es")

        assert result["language"] == "es"
        assert result["duration"] == 12.0
        assert len(result["segments"]) == 1
        seg = result["segments"][0]
        assert seg["text"] == "Hola mundo"
        assert len(seg["words"]) == 2
        assert seg["words"][0]["word"] == "Hola"

        call_args = mock_post.call_args
        assert call_args.kwargs["data"]["model"] == "whisper-1"

    @patch("autoedit.analysis.transcribe_remote.settings")
    def test_remote_falls_back_to_openrouter_key(self, mock_settings: Any) -> None:
        mock_settings.TRANSCRIPTION_REMOTE_API_KEY = ""
        mock_settings.OPENROUTER_API_KEY = "sk-or-fallback"

        from autoedit.analysis.transcribe_remote import _get_api_key

        assert _get_api_key() == "sk-or-fallback"

    @patch("autoedit.analysis.transcribe_remote.settings")
    def test_remote_raises_without_key(self, mock_settings: Any) -> None:
        mock_settings.TRANSCRIPTION_REMOTE_API_KEY = ""
        mock_settings.OPENROUTER_API_KEY = ""

        from autoedit.analysis.transcribe_remote import _get_api_key

        with pytest.raises(RuntimeError, match="requires"):
            _get_api_key()
