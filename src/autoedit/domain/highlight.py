"""Highlight and triage domain entities."""

from enum import StrEnum

from pydantic import BaseModel, Field

from autoedit.domain.ids import HighlightId, JobId, WindowId


class Intent(StrEnum):
    FAIL = "fail"
    WIN = "win"
    REACTION = "reaction"
    RAGE = "rage"
    FUNNY_MOMENT = "funny_moment"
    SKILL_PLAY = "skill_play"
    WHOLESOME = "wholesome"
    OTHER = "other"


class TriageResult(BaseModel):
    """Output from Triage VLM (Gemini Flash)."""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    keep: bool
    reasoning: str = Field(max_length=500)


class Highlight(BaseModel):
    id: HighlightId
    window_id: WindowId
    job_id: JobId
    intent: Intent
    triage_confidence: float
    triage_reasoning: str
    discarded: bool = False
    discard_reason: str | None = None
