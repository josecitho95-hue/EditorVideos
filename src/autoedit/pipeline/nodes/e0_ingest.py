"""E0 Ingest node: download VOD and chat."""

import shutil
from pathlib import Path

from loguru import logger

from autoedit.domain.ids import VodId, new_id
from autoedit.domain.job import JobStatus, Stage
from autoedit.ingest.twitch_chat import download_chat
from autoedit.ingest.twitch_vod import download_vod
from autoedit.pipeline.state import PipelineState
from autoedit.settings import settings
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.vods import VodRepository


async def run(state: PipelineState) -> None:
    """Execute E0 Ingest."""
    logger.info(f"[E0] Starting ingest for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.INGEST)

    # ------------------------------------------------------------------
    # Idempotency: if the job already has a vod_id and source.mp4 exists,
    # skip the download entirely (re-runs after partial failures are free).
    # ------------------------------------------------------------------
    if state.vod_id:
        vod_dir = settings.data_dir / "vods" / state.vod_id
        source_path = vod_dir / "source.mp4"
        if source_path.exists():
            logger.info(
                f"[E0] Skipping — source.mp4 already exists for VOD {state.vod_id}"
            )
            state.vod_dir = vod_dir
            return

    # Download VOD
    tmp_dir = settings.data_dir / "vods" / "tmp"
    info = download_vod(state.vod_url, tmp_dir)
    vod_id = VodId(str(info.get("id", new_id())))
    state.vod_id = vod_id

    vod_dir = settings.data_dir / "vods" / vod_id
    vod_dir.mkdir(parents=True, exist_ok=True)

    # Move downloaded file to final location
    downloaded = list(tmp_dir.glob("source.*"))
    if not downloaded:
        raise RuntimeError("VOD download failed: no file found in tmp dir")
    source_path = vod_dir / "source.mp4"
    downloaded[0].rename(source_path)
    # Remove tmp dir — use rmtree so residual yt-dlp temp files don't cause OSError
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # Download chat
    chat_path_raw: Path = vod_dir / "chat.jsonl"
    try:
        download_chat(state.vod_url, chat_path_raw)
    except Exception as exc:
        logger.warning(f"Chat download failed: {exc}, continuing without chat")

    # Persist VOD metadata
    duration = info.get("duration", 0)
    if isinstance(duration, str):
        duration = float(duration)

    VodRepository().create(
        vod_id=vod_id,
        url=state.vod_url,
        title=info.get("title"),
        streamer=info.get("uploader"),
        duration_sec=float(duration),
        recorded_at=info.get("upload_date"),
        language="auto",
        source_path=str(source_path),
        source_size_mb=round(source_path.stat().st_size / (1024 * 1024), 2) if source_path.exists() else None,
    )

    # Update job with vod_id
    JobRepository().update_vod_id(state.job_id, vod_id)
    state.vod_dir = vod_dir

    logger.info(f"[E0] Ingest complete: VOD {vod_id}, duration={duration}s")
