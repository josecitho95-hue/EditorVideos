"""Pipeline orchestrator that links nodes E0..E8."""

from pathlib import Path

from loguru import logger

from autoedit.domain.ids import VodId
from autoedit.domain.job import JobConfig, JobStatus
from autoedit.pipeline.nodes import (
    e0_ingest,
    e1_extract,
    e2_transcribe,
    e3_analyze,
    e4_score,
    e5_triage,
    e6_retrieve,
    e7_direct,
    e8_tts,
)
from autoedit.pipeline.state import PipelineState
from autoedit.storage.repositories.jobs import JobRepository

# Ordered list used by run_pipeline_from_e1 to know when to stop
_STAGES = ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"]


async def run_pipeline(job_id: str, vod_url: str, config: JobConfig) -> None:
    """Run the full pipeline from E0 to E8 (requires Twitch URL for E0)."""
    state = PipelineState(
        job_id=job_id,
        vod_url=vod_url,
        config=config,
    )

    try:
        await e0_ingest.run(state)
        await e1_extract.run(state)
        await e2_transcribe.run(state)
        await e3_analyze.run(state)
        await e4_score.run(state)
        await e5_triage.run(state)
        await e6_retrieve.run(state)
        await e7_direct.run(state)
        await e8_tts.run(state)

        JobRepository().update_status(job_id, JobStatus.DONE)
        logger.info(f"Pipeline complete for job {job_id}")
    except Exception as exc:
        logger.exception(f"Pipeline failed for job {job_id}: {exc}")
        JobRepository().update_status(job_id, JobStatus.FAILED, error=str(exc))
        raise


async def run_pipeline_from_e1(
    job_id: str,
    vod_id: VodId,
    vod_dir: Path,
    config: JobConfig,
    skip_tts: bool = False,
    until: str = "e8",
) -> None:
    """Run the pipeline from E1 onwards — for local files that skip E0 download.

    Args:
        job_id:    Job identifier (already in DB).
        vod_id:    VOD identifier (already in DB).
        vod_dir:   Directory containing ``source.mp4``.
        config:    Pipeline configuration.
        skip_tts:  If True, stop after E7 even if ``until`` says e8.
        until:     Last stage to run inclusive ('e1'..'e8').
    """
    until = until.lower().strip()
    if until not in _STAGES:
        raise ValueError(f"Invalid 'until' value {until!r}. Choose from: {_STAGES}")

    stop_after = _STAGES.index(until)
    if skip_tts and stop_after >= _STAGES.index("e8"):
        stop_after = _STAGES.index("e7")

    state = PipelineState(
        job_id=job_id,
        vod_url=f"file://{vod_dir / 'source.mp4'}",
        vod_id=str(vod_id),
        vod_dir=vod_dir,
        config=config,
    )

    node_map = [
        ("e1", e1_extract),
        ("e2", e2_transcribe),
        ("e3", e3_analyze),
        ("e4", e4_score),
        ("e5", e5_triage),
        ("e6", e6_retrieve),
        ("e7", e7_direct),
        ("e8", e8_tts),
    ]

    try:
        for stage_name, node in node_map:
            idx = _STAGES.index(stage_name)
            logger.info(f"[Orchestrator] Running {stage_name.upper()}")
            await node.run(state)
            if idx >= stop_after:
                logger.info(f"[Orchestrator] Reached --until {until.upper()}, stopping")
                break

        JobRepository().update_status(job_id, JobStatus.DONE)
        logger.info(f"Pipeline complete for job {job_id}")
    except Exception as exc:
        logger.exception(f"Pipeline failed at stage for job {job_id}: {exc}")
        JobRepository().update_status(job_id, JobStatus.FAILED, error=str(exc))
        raise
