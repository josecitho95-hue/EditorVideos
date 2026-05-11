"""Database engine and SQLModel table definitions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Column, Engine, ForeignKey, String, event, text
from sqlmodel import Field, Session, SQLModel, create_engine

from autoedit.settings import settings

# ---------------------------------------------------------------------------
# Singleton engine — created once per process, shared by all sessions.
# ---------------------------------------------------------------------------
_engine: Engine | None = None


def _attach_pragmas(engine: Engine) -> None:
    """Register connection-level SQLite pragmas on *engine* via an event listener.

    Called for both the singleton engine and any injected engine so that
    tests using an in-memory engine get the same pragma configuration.
    WAL is silently ignored by in-memory SQLite (it stays in "memory" mode).
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")


def get_engine() -> Engine:
    """Return (or create) the shared SQLAlchemy engine with WAL + FK enabled."""
    global _engine
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite:///{settings.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        _attach_pragmas(engine)
        _engine = engine
    return _engine


def get_session() -> Session:
    """Return a new :class:`Session` bound to the singleton engine.

    Use as a context manager::

        with get_session() as session:
            session.add(model)
            session.commit()
    """
    return Session(get_engine())


# ---------------------------------------------------------------------------
# Table models
# ---------------------------------------------------------------------------


class JobModel(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    vod_url: str
    vod_id: str | None = Field(default=None, foreign_key="vods.id")
    status: str
    current_stage: str | None = None
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    total_cost_usd: float = Field(default=0.0)


class VodModel(SQLModel, table=True):
    __tablename__ = "vods"

    id: str = Field(primary_key=True)
    url: str = Field(unique=True)
    title: str | None = None
    streamer: str | None = None
    duration_sec: float
    recorded_at: str | None = None
    language: str = Field(default="auto")
    # Local file paths written during pipeline execution
    source_path: str | None = None
    audio_path: str | None = None
    chat_path: str | None = None
    transcript_path: str | None = None   # E2 output (JSON)
    scenes_path: str | None = None        # E3 scene detect output (JSON)
    signals_path: str | None = None       # E3/E4 signals output (Parquet)
    source_size_mb: float | None = None
    deleted_source: int = Field(default=0)
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: str


class RunStepModel(SQLModel, table=True):
    __tablename__ = "run_steps"

    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(
        sa_column=Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    )
    stage: str
    status: str
    input_hash: str | None = None
    output_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_sec: float | None = None
    cost_usd: float = Field(default=0.0)
    tokens_in: int | None = None
    tokens_out: int | None = None
    model: str | None = None
    error: str | None = None


class TranscriptSegmentModel(SQLModel, table=True):
    __tablename__ = "transcript_segments"

    id: int | None = Field(default=None, primary_key=True)
    vod_id: str = Field(foreign_key="vods.id")
    start_sec: float
    end_sec: float
    text: str
    speaker: str | None = None
    avg_logprob: float | None = None


class TranscriptWordModel(SQLModel, table=True):
    __tablename__ = "transcript_words"

    id: int | None = Field(default=None, primary_key=True)
    segment_id: int = Field(foreign_key="transcript_segments.id")
    word: str
    start_sec: float
    end_sec: float
    score: float | None = None


class WindowModel(SQLModel, table=True):
    __tablename__ = "windows"

    id: str = Field(primary_key=True)
    job_id: str = Field(
        sa_column=Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    )
    vod_id: str = Field(foreign_key="vods.id")
    start_sec: float
    end_sec: float
    score: float
    score_breakdown: dict[str, Any] = Field(sa_column=Column(JSON))
    rank: int
    transcript_excerpt: str = Field(default="")


class HighlightModel(SQLModel, table=True):
    __tablename__ = "highlights"

    id: str = Field(primary_key=True)
    window_id: str = Field(foreign_key="windows.id")
    job_id: str = Field(
        sa_column=Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    )
    intent: str
    triage_confidence: float
    triage_reasoning: str | None = None
    discarded: int = Field(default=0)
    discard_reason: str | None = None


class EditDecisionModel(SQLModel, table=True):
    __tablename__ = "edit_decisions"

    id: str = Field(primary_key=True)
    highlight_id: str = Field(foreign_key="highlights.id", unique=True)
    plan: dict[str, Any] = Field(sa_column=Column(JSON))
    model: str
    cost_usd: float
    created_at: str


class ClipModel(SQLModel, table=True):
    __tablename__ = "clips"

    id: str = Field(primary_key=True)
    highlight_id: str | None = Field(default=None, foreign_key="highlights.id")
    job_id: str = Field(foreign_key="jobs.id")
    output_path: str
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    file_size_mb: float | None = None
    sha256: str | None = None
    rendered_at: str
    user_rating: int | None = None
    user_note: str | None = None


class AssetModel(SQLModel, table=True):
    __tablename__ = "assets"

    id: str = Field(primary_key=True)
    kind: str
    file_path: str
    sha256: str
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    sample_rate_hz: int | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    intent_affinity: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    description: str | None = None
    embedding_indexed: int = Field(default=0)
    license: str | None = None
    source_url: str | None = None
    added_at: str


class AssetUsageModel(SQLModel, table=True):
    __tablename__ = "asset_usages"

    id: int | None = Field(default=None, primary_key=True)
    asset_id: str = Field(foreign_key="assets.id")
    clip_id: str = Field(foreign_key="clips.id")
    timeline_start: float
    timeline_end: float
    role: str


class NarrationModel(SQLModel, table=True):
    __tablename__ = "narrations"

    # Primary key is SHA256(voice_id + ":" + text)[:32] — acts as the cache key.
    id: str = Field(primary_key=True)
    text: str
    voice_id: str
    audio_path: str
    duration_sec: float
    sample_rate_hz: int
    model: str
    generated_at: str
    used_count: int = Field(default=0)


class VoiceProfileModel(SQLModel, table=True):
    """Registered voice profile for TTS voice cloning (F5-TTS reference audio)."""

    __tablename__ = "voice_profiles"

    id: str = Field(primary_key=True)          # user-defined slug, e.g. "me_v1"
    display_name: str                           # human label, e.g. "Jose — gaming voice"
    ref_audio_path: str                         # absolute path to 24kHz mono WAV (>= 15s)
    ref_text: str                               # transcript of the reference audio
    duration_sec: float = Field(default=0.0)
    sample_rate_hz: int = Field(default=24000)
    created_at: str = Field(default="")


class CostEntryModel(SQLModel, table=True):
    __tablename__ = "cost_entries"

    id: int | None = Field(default=None, primary_key=True)
    job_id: str | None = Field(default=None, foreign_key="jobs.id")
    stage: str | None = None
    provider: str
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    usd: float
    occurred_at: str


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


def init_db(engine: Engine | None = None) -> None:
    """Create all tables if they don't exist (idempotent).

    Args:
        engine: Optional engine to use instead of the global singleton.
                Pass an in-memory engine in tests for full isolation.
                The same WAL/FK pragmas are applied to any injected engine.
    """
    target = engine or get_engine()
    if engine is not None:
        # Attach pragmas to the injected engine the same way get_engine() does.
        # For in-memory SQLite, WAL is silently ignored; FK and synchronous take effect.
        _attach_pragmas(engine)
    SQLModel.metadata.create_all(target)


def run_migrations(engine: Engine | None = None) -> None:
    """Alias for :func:`init_db` — kept for test and CLI compatibility."""
    init_db(engine=engine)
