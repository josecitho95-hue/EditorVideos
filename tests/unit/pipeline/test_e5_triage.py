"""Tests for E5 Triage node."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from autoedit.domain.highlight import Intent
from autoedit.domain.ids import VodId, WindowId, new_id
from autoedit.domain.job import JobConfig
from autoedit.domain.signals import WindowCandidate
from autoedit.pipeline.nodes import e5_triage
from autoedit.pipeline.state import PipelineState


class TestBuildTriagePrompt:
    """TC-TRI-001 — prompt construction."""

    def test_prompt_includes_window_metadata(self, tmp_path: Path) -> None:
        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={"audio": 0.9, "chat": 0.75, "transcript": 0.8, "scene": 0.7},
            rank=1,
            transcript_excerpt="Test excerpt",
        )
        prompt = e5_triage._build_triage_prompt(window, None)
        assert "10.0s to 40.0s" in prompt
        assert "0.82" in prompt
        assert "Test excerpt" in prompt

    def test_prompt_reads_transcript_file(self, tmp_path: Path) -> None:
        transcript_path = tmp_path / "transcript.json"
        transcript_path.write_text(
            json.dumps({
                "segments": [
                    {"start": 12.0, "end": 15.0, "text": "Woah qué pasó"},
                    {"start": 20.0, "end": 25.0, "text": "No no no NO"},
                ]
            })
        )
        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={},
            rank=1,
            transcript_excerpt="fallback",
        )
        prompt = e5_triage._build_triage_prompt(window, str(transcript_path))
        assert "Woah qué pasó" in prompt
        assert "No no no NO" in prompt


class TestTriageWindow:
    """TC-TRI-002 — LLM response parsing."""

    @patch("autoedit.pipeline.nodes.e5_triage.openrouter.chat")
    async def test_valid_json_response(self, mock_chat: AsyncMock) -> None:
        mock_chat.return_value = MagicMock(
            content=json.dumps({
                "intent": "fail",
                "confidence": 0.92,
                "keep": True,
                "reasoning": "Streamer falla dramaticamente",
            })
        )
        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={},
            rank=1,
            transcript_excerpt="test",
        )
        result = await e5_triage._triage_window(window, None)
        assert result.intent == Intent.FAIL
        assert result.confidence == 0.92
        assert result.keep is True
        assert "falla" in result.reasoning

    @patch("autoedit.pipeline.nodes.e5_triage.openrouter.chat")
    async def test_invalid_json_fallback(self, mock_chat: AsyncMock) -> None:
        mock_chat.return_value = MagicMock(content="not json")
        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={},
            rank=1,
            transcript_excerpt="test",
        )
        result = await e5_triage._triage_window(window, None)
        assert result.intent == Intent.OTHER
        assert result.confidence == 0.0
        assert result.keep is False

    @patch("autoedit.pipeline.nodes.e5_triage.openrouter.chat")
    async def test_unknown_intent_fallback(self, mock_chat: AsyncMock) -> None:
        mock_chat.return_value = MagicMock(
            content=json.dumps({
                "intent": "nonexistent",
                "confidence": 0.5,
                "keep": True,
                "reasoning": "test",
            })
        )
        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={},
            rank=1,
            transcript_excerpt="test",
        )
        result = await e5_triage._triage_window(window, None)
        assert result.intent == Intent.OTHER


class TestTriageRun:
    """TC-TRI-003 — full node integration."""

    @patch("autoedit.pipeline.nodes.e5_triage.openrouter.chat")
    @patch("autoedit.pipeline.nodes.e5_triage.WindowRepository")
    @patch("autoedit.pipeline.nodes.e5_triage.HighlightRepository")
    async def test_run_creates_highlights(self, mock_repo_cls: Any, mock_win_repo_cls: Any, mock_chat: AsyncMock) -> None:
        mock_chat.return_value = MagicMock(
            content=json.dumps({
                "intent": "fail",
                "confidence": 0.92,
                "keep": True,
                "reasoning": "Epic fail",
            })
        )

        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={},
            rank=1,
            transcript_excerpt="test",
        )

        mock_win_repo = MagicMock()
        mock_win_repo.list_by_job.return_value = [window]
        mock_win_repo_cls.return_value = mock_win_repo

        mock_highlight_repo = MagicMock()
        mock_repo_cls.return_value = mock_highlight_repo

        state = PipelineState(
            job_id="job-123",
            vod_url="mock://test",
            config=JobConfig(target_clip_count=2),
        )

        await e5_triage.run(state)

        mock_win_repo.list_by_job.assert_called_once_with("job-123")
        mock_highlight_repo.create_many.assert_called_once()
        highlights = mock_highlight_repo.create_many.call_args.args[0]
        assert len(highlights) == 1
        assert highlights[0].intent == Intent.FAIL
        assert highlights[0].discarded is False

    @patch("autoedit.pipeline.nodes.e5_triage.openrouter.chat")
    @patch("autoedit.pipeline.nodes.e5_triage.WindowRepository")
    @patch("autoedit.pipeline.nodes.e5_triage.HighlightRepository")
    async def test_run_discards_low_confidence(self, mock_repo_cls: Any, mock_win_repo_cls: Any, mock_chat: AsyncMock) -> None:
        mock_chat.return_value = MagicMock(
            content=json.dumps({
                "intent": "other",
                "confidence": 0.2,
                "keep": False,
                "reasoning": "Not interesting",
            })
        )

        window = WindowCandidate(
            id=WindowId(new_id()),
            vod_id=VodId("v1"),
            start_sec=10.0,
            end_sec=40.0,
            score=0.82,
            score_breakdown={},
            rank=1,
            transcript_excerpt="test",
        )

        mock_win_repo = MagicMock()
        mock_win_repo.list_by_job.return_value = [window]
        mock_win_repo_cls.return_value = mock_win_repo

        mock_highlight_repo = MagicMock()
        mock_repo_cls.return_value = mock_highlight_repo

        state = PipelineState(
            job_id="job-456",
            vod_url="mock://test",
            config=JobConfig(target_clip_count=2),
        )

        await e5_triage.run(state)

        highlights = mock_highlight_repo.create_many.call_args.args[0]
        assert highlights[0].discarded is True
        assert "Not interesting" in highlights[0].discard_reason
