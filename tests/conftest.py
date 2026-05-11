"""
Global fixtures for AutoEdit AI test suite.

Scope guide:
  session  → heavy resources created once per run (WAV files, session-wide mocks)
  function → isolated state per test (DB sessions, entity instances)
"""
from __future__ import annotations

import json
import struct
import wave
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from autoedit.domain.edit_decision import EditDecision
from autoedit.domain.highlight import Highlight
from autoedit.domain.ids import AssetId, HighlightId, JobId, VodId, WindowId
from autoedit.domain.job import Job, JobConfig
from autoedit.domain.signals import WindowCandidate

# ---------------------------------------------------------------------------
# Database — SQLite in-memory, isolated per test function
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    with Session(db_engine) as session:
        yield session


# Keep legacy name for compatibility
@pytest.fixture(name="session")
def session_fixture(db_session: Session) -> Session:
    return db_session


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def data_dir(tmp_path: Path) -> Path:
    for sub in ["vods", "assets/visual", "assets/audio", "cache/tts", "cache/triage", "voice_ref", "tmp"]:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------


def _make_silent_wav(path: Path, duration_sec: float, sample_rate: int = 24000) -> Path:
    n = int(duration_sec * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return path


@pytest.fixture(scope="session")
def voice_ref_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """35 s of silence at 24 kHz — simulates the user's voice reference file."""
    p = tmp_path_factory.mktemp("voice") / "me.wav"
    return _make_silent_wav(p, duration_sec=35.0, sample_rate=24000)


@pytest.fixture(scope="session")
def short_audio_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30 s, 16 kHz, mono WAV with an amplitude spike at t=15 s (simulates a loud moment)."""
    sr = 16_000
    dur = 30
    samples = np.zeros(sr * dur, dtype=np.int16)
    t = np.arange(sr, dtype=np.float32)
    spike = (np.sin(2 * np.pi * 440 * t / sr) * 28_000).astype(np.int16)
    samples[15 * sr : 16 * sr] = spike

    p = tmp_path_factory.mktemp("audio") / "audio.wav"
    with wave.open(str(p), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())
    return p


# ---------------------------------------------------------------------------
# Domain entity factories
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_job_config() -> JobConfig:
    return JobConfig(
        target_clip_count=5,
        clip_min_duration_sec=15.0,
        clip_max_duration_sec=60.0,
        director_model="deepseek/deepseek-chat-v3",
        triage_model="google/gemini-2.5-flash",
        language="es",
        delete_source_after=False,
    )


@pytest.fixture
def sample_job(sample_job_config: JobConfig) -> Job:
    from autoedit.domain.ids import new_id
    from autoedit.domain.job import JobStatus

    return Job(
        id=JobId(new_id()),
        vod_url="mock://twitch.tv/videos/123456789",
        status=JobStatus.QUEUED,
        config=sample_job_config,
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def sample_window(sample_job: Job) -> WindowCandidate:
    from autoedit.domain.ids import new_id

    return WindowCandidate(
        id=WindowId(new_id()),
        vod_id=VodId("123456789"),
        start_sec=10.0,
        end_sec=45.0,
        score=0.82,
        score_breakdown={"audio": 0.9, "chat": 0.75, "transcript": 0.8, "scene": 0.7},
        rank=1,
        transcript_excerpt="Woah qué fue eso, no no no NO!",
    )


@pytest.fixture
def sample_highlight(sample_window: WindowCandidate, sample_job: Job) -> Highlight:
    from autoedit.domain.highlight import Intent
    from autoedit.domain.ids import new_id

    return Highlight(
        id=HighlightId(new_id()),
        window_id=sample_window.id,
        job_id=sample_job.id,
        intent=Intent.FAIL,
        triage_confidence=0.91,
        triage_reasoning="Streamer falla dramáticamente, el chat explota con LULs.",
        discarded=False,
    )


@pytest.fixture
def sample_edit_decision(sample_highlight: Highlight) -> EditDecision:
    from autoedit.domain.edit_decision import (
        MemeOverlay,
        NarrationCue,
        SfxCue,
        SubtitleStyle,
        Trim,
        ZoomEvent,
        ZoomKind,
    )

    return EditDecision(
        highlight_id=sample_highlight.id,
        title="El fail más épico del día",
        trim=Trim(start_sec=11.0, end_sec=48.0, reason="Contexto + reacción completa."),
        zoom_events=[ZoomEvent(at_sec=15.0, duration_sec=0.5, kind=ZoomKind.PUNCH_IN, intensity=1.8)],
        meme_overlays=[
            MemeOverlay(
                asset_id=AssetId("asset_oof_001"),
                at_sec=16.0,
                duration_sec=1.5,
                position="center",
                scale=0.4,
                enter_anim="pop",
                exit_anim="fade",
            )
        ],
        sfx_cues=[SfxCue(asset_id=AssetId("sfx_fail_001"), at_sec=15.5, volume_db=-6.0)],
        narration_cues=[
            NarrationCue(
                text="Se lo veía venir desde el principio.",
                at_sec=20.0,
                voice_id="me_v1",
                duck_main_audio_db=-10.0,
            )
        ],
        subtitle_style=SubtitleStyle(),
        rationale="Zoom punch-in en el clímax, meme OOF clásico, SFX dramático.",
    )


# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------

MOCK_TRIAGE_CONTENT = json.dumps({
    "intent": "fail",
    "confidence": 0.91,
    "keep": True,
    "reasoning": "Streamer falla dramáticamente, el chat explota con LULs.",
})

MOCK_TRIAGE_RESPONSE = {
    "id": "chatcmpl-triage-test",
    "object": "chat.completion",
    "choices": [{"message": {"role": "assistant", "content": MOCK_TRIAGE_CONTENT}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 800, "completion_tokens": 80, "total_tokens": 880},
}


def make_director_llm_response(edit_decision_json: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-director-test",
        "object": "chat.completion",
        "choices": [
            {"message": {"role": "assistant", "content": edit_decision_json}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 500, "total_tokens": 2500},
    }


# ---------------------------------------------------------------------------
# Mock TTS engine — no GPU required in tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tts_engine() -> AsyncMock:
    """F5-TTS mock that returns silent audio proportional to text length."""

    async def _generate(text: str, voice_ref: str, **kwargs: Any) -> tuple[np.ndarray, int]:
        sr = 24_000
        duration = max(0.5, len(text) * 0.05)
        return np.zeros(int(sr * duration), dtype=np.float32), sr

    engine = AsyncMock()
    engine.generate.side_effect = _generate
    return engine
