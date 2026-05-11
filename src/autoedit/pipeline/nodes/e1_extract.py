"""E1 Extract node: extract audio and detect scenes."""

import json
import subprocess

from loguru import logger

from autoedit.domain.job import JobStatus, Stage
from autoedit.pipeline.state import PipelineState
from autoedit.settings import settings
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.vods import VodRepository


async def run(state: PipelineState) -> None:
    """Execute E1 Extract."""
    logger.info(f"[E1] Starting extract for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.EXTRACT)

    if not state.vod_dir:
        raise RuntimeError("VOD directory not set")

    source_path = state.vod_dir / "source.mp4"
    audio_path = state.vod_dir / "audio.wav"
    scenes_path = state.vod_dir / "scenes.json"

    # --- Idempotency: skip heavy work if outputs already exist ---
    if audio_path.exists() and scenes_path.exists():
        logger.info(f"[E1] Skipping — audio.wav and scenes.json already exist in {state.vod_dir}")
        state.audio_path = str(audio_path)
        state.scenes_path = str(scenes_path)
        VodRepository().update_paths(
            vod_id=state.vod_id,
            audio_path=str(audio_path),
            chat_path=str(state.vod_dir / "chat.jsonl") if (state.vod_dir / "chat.jsonl").exists() else None,
        )
        return

    # Extract audio with FFmpeg
    logger.info("Extracting audio with FFmpeg...")
    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-i", str(source_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr}")

    state.audio_path = str(audio_path)

    # Detect scenes with PySceneDetect (via subprocess for simplicity)
    logger.info("Detecting scenes with PySceneDetect...")
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(source_path), ContentDetector(threshold=27.0))
        scenes_data = [
            {
                "shot_id": i,
                "start_sec": float(scene[0].get_seconds()),
                "end_sec": float(scene[1].get_seconds()),
                "is_cut": True,
            }
            for i, scene in enumerate(scenes)
        ]
        with open(scenes_path, "w") as f:
            json.dump(scenes_data, f, indent=2)
        state.scenes_path = str(scenes_path)
    except Exception as exc:
        logger.warning(f"Scene detection failed: {exc}, continuing without scenes")
        scenes_data = []

    # Update VOD paths
    if not state.vod_id:
        raise RuntimeError("vod_id not set")
    VodRepository().update_paths(
        vod_id=state.vod_id,
        audio_path=str(audio_path),
        chat_path=str(state.vod_dir / "chat.jsonl") if (state.vod_dir / "chat.jsonl").exists() else None,
    )

    logger.info(f"[E1] Extract complete: audio={audio_path}, scenes={len(scenes_data)}")


# Alias for backward compatibility with legacy tests
def run_e1_extract(source_path: str, work_dir: str) -> None:
    raise NotImplementedError("run_e1_extract legacy API removed — use run(state) async")
