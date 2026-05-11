"""Tests for Job domain entity."""

from datetime import UTC, datetime

from autoedit.domain.ids import JobId, new_id
from autoedit.domain.job import Job, JobConfig, JobStatus


def test_job_config_defaults() -> None:
    cfg = JobConfig()
    assert cfg.clip_max_duration_sec == 45.0
    assert cfg.output_formats == ["youtube"]
    assert cfg.output_resolution == (1920, 1080)
    assert cfg.delete_source_after is True


def test_job_creation() -> None:
    job = Job(
        id=JobId(new_id()),
        vod_url="https://twitch.tv/videos/12345",
        status=JobStatus.QUEUED,
        config=JobConfig(),
        created_at=datetime.now(UTC),
    )
    assert job.total_cost_usd == 0.0
    assert job.vod_id is None
