"""Domain package exports."""

from autoedit.domain.clip import Asset, AssetKind, Clip
from autoedit.domain.edit_decision import EditDecision
from autoedit.domain.highlight import Highlight, Intent, TriageResult
from autoedit.domain.ids import new_id
from autoedit.domain.job import Job, JobConfig, JobStatus, Stage
from autoedit.domain.signals import AudioSignal, ChatSignal, SceneSignal, WindowCandidate

__all__ = [
    "new_id",
    "Job",
    "JobConfig",
    "JobStatus",
    "Stage",
    "WindowCandidate",
    "AudioSignal",
    "ChatSignal",
    "SceneSignal",
    "Highlight",
    "Intent",
    "TriageResult",
    "EditDecision",
    "Clip",
    "Asset",
    "AssetKind",
]
