"""E2 Transcribe node."""

from loguru import logger

from autoedit.analysis.transcribe import transcribe_audio
from autoedit.domain.job import JobStatus, Stage
from autoedit.pipeline.state import PipelineState
from autoedit.storage.repositories.jobs import JobRepository


async def run(state: PipelineState) -> None:
    """Execute E2 Transcribe."""
    logger.info(f"[E2] Starting transcription for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.TRANSCRIBE)

    if not state.audio_path:
        raise RuntimeError("Audio path not set")
    if not state.vod_dir:
        raise RuntimeError("VOD directory not set")

    transcript_path = state.vod_dir / "transcript.json"

    # --- Idempotency: skip Whisper if transcript already exists ---
    if transcript_path.exists():
        logger.info(f"[E2] Skipping — transcript.json already exists ({transcript_path})")
        state.transcript_path = str(transcript_path)
        import json
        with open(transcript_path, encoding="utf-8") as f:
            cached = json.load(f)
        logger.info(
            f"[E2] Loaded cached transcript: {len(cached.get('segments', []))} segments, "
            f"lang={cached.get('language')}"
        )
        return

    result = transcribe_audio(
        audio_path=state.audio_path,
        output_path=str(transcript_path),
        language=state.config.language,
    )
    state.transcript_path = str(transcript_path)

    logger.info(
        f"[E2] Transcription complete: {len(result.get('segments', []))} segments, "
        f"lang={result.get('language')}"
    )
