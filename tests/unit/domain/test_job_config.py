from __future__ import annotations

"""
TC-DOM-001, TC-DOM-002
Tests for JobConfig validation, defaults, JobStatus enum, and Stage enum.
"""

import pytest
from pydantic import ValidationError

from autoedit.domain.job import JobConfig, JobStatus, Stage


class TestJobConfigValidation:
    """TC-DOM-001 — boundary validation on target_clip_count."""

    def test_valid_clip_count(self) -> None:
        cfg = JobConfig(target_clip_count=10)
        assert cfg.target_clip_count == 10

    def test_min_clip_count(self) -> None:
        cfg = JobConfig(target_clip_count=1)
        assert cfg.target_clip_count == 1

    def test_max_clip_count(self) -> None:
        cfg = JobConfig(target_clip_count=30)
        assert cfg.target_clip_count == 30

    def test_zero_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            JobConfig(target_clip_count=0)
        assert "target_clip_count" in str(exc_info.value)

    def test_31_raises(self) -> None:
        with pytest.raises(ValidationError):
            JobConfig(target_clip_count=31)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            JobConfig(target_clip_count=-5)


class TestJobConfigDefaults:
    """TC-DOM-002 — default values are correct."""

    def setup_method(self) -> None:
        self.cfg = JobConfig()

    def test_clip_max_duration_sec(self) -> None:
        assert self.cfg.clip_max_duration_sec == 45.0

    def test_clip_min_duration_sec(self) -> None:
        assert self.cfg.clip_min_duration_sec == 15.0

    def test_output_resolution(self) -> None:
        assert self.cfg.output_resolution == (1920, 1080)

    def test_output_fps(self) -> None:
        assert self.cfg.output_fps == 30

    def test_output_codec(self) -> None:
        assert self.cfg.output_codec == "h264_nvenc"

    def test_director_model(self) -> None:
        assert self.cfg.director_model == "deepseek/deepseek-chat-v3"

    def test_triage_model(self) -> None:
        assert self.cfg.triage_model == "google/gemini-2.5-flash"

    def test_language(self) -> None:
        assert self.cfg.language == "es"

    def test_enable_narration(self) -> None:
        assert self.cfg.enable_narration is True

    def test_enable_memes(self) -> None:
        assert self.cfg.enable_memes is True

    def test_enable_sfx(self) -> None:
        assert self.cfg.enable_sfx is True

    def test_delete_source_after(self) -> None:
        assert self.cfg.delete_source_after is True


class TestJobStatus:
    """TC-DOM-001 — JobStatus enum values."""

    def test_all_statuses_are_strings(self) -> None:
        for member in JobStatus:
            assert isinstance(member.value, str), (
                f"JobStatus.{member.name} value is not a string"
            )

    def test_expected_statuses_exist(self) -> None:
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.DONE.value == "done"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"
        assert JobStatus.PAUSED.value == "paused"


class TestStageEnum:
    """TC-DOM-001 — Stage enum shape."""

    def test_stage_count(self) -> None:
        assert len(Stage) == 11, (
            f"Expected 11 stages, got {len(Stage)}: {[s.name for s in Stage]}"
        )

    def test_stage_values_start_with_e(self) -> None:
        for stage in Stage:
            assert stage.value.startswith("E"), (
                f"Stage {stage.name!r} value {stage.value!r} does not start with 'E'"
            )
