"""Pipeline state shared between nodes."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoedit.domain.job import JobConfig


@dataclass
class PipelineState:
    """Mutable state passed through pipeline nodes."""

    job_id: str
    vod_url: str
    vod_id: str | None = None
    config: JobConfig = field(default_factory=JobConfig)
    vod_dir: Path | None = None
    audio_path: str | None = None
    chat_path: str | None = None
    transcript_path: str | None = None
    scenes_path: str | None = None
    signals_path: str | None = None
    retrieved_assets: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    narration_paths: dict[str, str] = field(default_factory=dict)
    error: str | None = None
