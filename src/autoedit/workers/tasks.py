"""arq worker tasks."""

from typing import Any

from autoedit.domain.job import JobConfig
from autoedit.pipeline.orchestrator import run_pipeline


async def process_job(ctx: dict[str, Any], job_id: str, vod_url: str, config_dict: dict[str, Any]) -> None:
    """arq task: process a job through the pipeline."""
    config = JobConfig.model_validate(config_dict)
    await run_pipeline(job_id, vod_url, config)
