"""EditDecision domain entity — the core output of the Director agent."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from autoedit.domain.ids import AssetId, HighlightId


class ZoomKind(StrEnum):
    SUBJECT_FACE = "subject_face"
    REGION = "region"
    PUNCH_IN = "punch_in"


class Trim(BaseModel):
    start_sec: float
    end_sec: float
    reason: str = Field(default="", max_length=200)


class ZoomEvent(BaseModel):
    at_sec: float
    duration_sec: float = Field(ge=0.1, le=5.0)
    kind: ZoomKind
    intensity: float = Field(default=1.5, ge=1.0, le=2.5)

    @field_validator("intensity", mode="before")
    @classmethod
    def clamp_intensity(cls, v: float) -> float:
        """Clamp LLM output to valid range [1.0, 2.5]."""
        return max(1.0, min(2.5, float(v)))
    region: tuple[float, float, float, float] | None = None


class MemeOverlay(BaseModel):
    asset_id: AssetId
    at_sec: float
    duration_sec: float = Field(ge=0.3, le=8.0)
    position: str = Field(default="center")
    scale: float = Field(default=0.4, ge=0.1, le=1.0)
    enter_anim: str = "pop"
    exit_anim: str = "fade"


class SfxCue(BaseModel):
    asset_id: AssetId
    at_sec: float
    volume_db: float = Field(default=-6.0, ge=-30.0, le=6.0)


class NarrationCue(BaseModel):
    text: str = Field(max_length=300, min_length=1)
    at_sec: float
    voice_id: str = "me_v1"
    duck_main_audio_db: float = -10.0


class SubtitleStyle(BaseModel):
    font_family: str = "Arial Black"
    font_size_px: int = 72
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_px: int = 4
    position: str = "lower_third"
    karaoke_highlight_color: str = "#FFD700"


class EditDecision(BaseModel):
    """Complete plan to render a highlight."""

    highlight_id: HighlightId
    title: str = Field(max_length=80)
    trim: Trim
    zoom_events: list[ZoomEvent] = Field(default_factory=list, max_length=15)
    meme_overlays: list[MemeOverlay] = Field(default_factory=list, max_length=8)
    sfx_cues: list[SfxCue] = Field(default_factory=list, max_length=10)
    narration_cues: list[NarrationCue] = Field(default_factory=list, max_length=4)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    background_music_asset_id: AssetId | None = None
    rationale: str = Field(max_length=600)
