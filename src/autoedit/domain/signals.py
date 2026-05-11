"""Signal and window domain entities."""

from pydantic import BaseModel, Field

from autoedit.domain.ids import VodId, WindowId


class AudioSignal(BaseModel):
    """One entry per second of the VOD."""

    t_sec: float
    rms_db: float
    loudness_lufs: float
    pitch_hz: float | None = None
    laughter_prob: float = Field(ge=0.0, le=1.0, default=0.0)


class ChatSignal(BaseModel):
    t_sec: float
    msg_per_sec: float
    unique_users: int
    keyword_score: float
    emote_score: float = Field(ge=0.0, le=1.0, default=0.0)   # weighted emote intensity (normalised)
    spike_score: float = Field(ge=0.0, le=1.0, default=0.0)   # burst above 30s rolling baseline
    sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)


class SceneSignal(BaseModel):
    t_sec: float
    is_cut: bool
    shot_id: int


class WindowCandidate(BaseModel):
    id: WindowId
    vod_id: VodId
    start_sec: float
    end_sec: float
    score: float = Field(ge=0.0, le=1.0)
    score_breakdown: dict[str, float]
    rank: int
    transcript_excerpt: str
