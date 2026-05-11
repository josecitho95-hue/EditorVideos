"""Job domain entities and configuration."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from autoedit.domain.ids import JobId, VodId


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Stage(StrEnum):
    INGEST = "E0_ingest"
    EXTRACT = "E1_extract"
    TRANSCRIBE = "E2_transcribe"
    ANALYZE = "E3_analyze"
    SCORE = "E4_score"
    TRIAGE = "E5_triage"
    RETRIEVE = "E6_retrieve"
    DIRECT = "E7_direct"
    TTS = "E8_tts"
    RENDER = "E9_render"
    FINALIZE = "E10_finalize"


class JobConfig(BaseModel):
    target_clip_count: int = Field(default=10, ge=1, le=30)
    clip_min_duration_sec: float = 15.0
    clip_max_duration_sec: float = 45.0
    output_formats: list[str] = Field(default_factory=lambda: ["youtube"])
    output_resolution: tuple[int, int] = (1920, 1080)
    output_fps: int = 30
    output_codec: str = "h264_nvenc"
    enable_narration: bool = True
    enable_memes: bool = True
    enable_sfx: bool = True
    director_model: str = "deepseek/deepseek-chat-v3"
    triage_model: str = "google/gemini-2.5-flash"
    language: str = "es"
    delete_source_after: bool = True


class Job(BaseModel):
    id: JobId
    vod_url: str
    vod_id: VodId | None = None
    status: JobStatus
    current_stage: Stage | None = None
    config: JobConfig
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_cost_usd: float = 0.0
