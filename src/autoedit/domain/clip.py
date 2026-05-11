"""Clip and asset domain entities."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from autoedit.domain.ids import AssetId, ClipId, HighlightId, JobId


class Clip(BaseModel):
    id: ClipId
    highlight_id: HighlightId
    job_id: JobId
    output_path: str
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    file_size_mb: float | None = None
    sha256: str | None = None
    rendered_at: datetime
    user_rating: int | None = None
    user_note: str | None = None


class AssetKind(StrEnum):
    VISUAL_IMAGE = "visual_image"
    VISUAL_VIDEO = "visual_video"
    AUDIO_SFX = "audio_sfx"
    MEME = "meme"


class Asset(BaseModel):
    id: AssetId
    kind: AssetKind
    file_path: str
    sha256: str
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    sample_rate_hz: int | None = None
    tags: list[str]
    intent_affinity: list[str]
    description: str | None = None
    license: str = "owned"
    source_url: str | None = None
