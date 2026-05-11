"""E8 TTS node — generate narration audio with F5-TTS voice cloning.

Flow
----
1. Load all EditDecisions for the current job.
2. For each narration cue: check NarrationCache (SQLite hit = ~0 ms).
3. On miss: F5TTSEngine synthesizes via F5-TTS (local GPU, ~2-5s/clip).
4. Falls back to a silent WAV if synthesis fails (pipeline never crashes).
5. Writes ``state.narration_paths`` dict mapping "highlight_id_at_sec" -> wav path.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from loguru import logger

from autoedit.domain.job import JobStatus, Stage
from autoedit.pipeline.state import PipelineState
from autoedit.settings import settings
from autoedit.storage.repositories.edit_decisions import EditDecisionRepository
from autoedit.storage.repositories.jobs import JobRepository


def _write_silent_wav(path: Path, duration_sec: float, sample_rate: int = 24000) -> None:
    """Write a silent mono WAV placeholder."""
    n_samples = int(max(0.1, duration_sec) * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))


async def run(state: PipelineState) -> None:
    """Execute E8 TTS (narration generation)."""
    logger.info(f"[E8] Starting TTS for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.TTS)

    if not state.vod_dir:
        logger.warning("[E8] No VOD directory, skipping TTS")
        return

    decisions = EditDecisionRepository().list_by_job(state.job_id)
    if not decisions:
        logger.info("[E8] No edit decisions to generate narration for")
        return

    # Count cues upfront to log properly
    total_cues = sum(len(d.narration_cues) for d in decisions)
    if total_cues == 0:
        logger.info("[E8] No narration cues in any edit decision, skipping")
        return

    logger.info(f"[E8] Processing {total_cues} narration cue(s) across {len(decisions)} decisions")

    # Set up NarrationCache with F5TTSEngine
    from autoedit.tts.f5_engine import F5TTSEngine
    from autoedit.tts.narration_cache import NarrationCache

    cache_dir = settings.data_dir / "narrations"
    engine = F5TTSEngine()
    cache = NarrationCache(cache_dir=cache_dir, tts_engine=engine)

    tts_dir = state.vod_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)

    state.narration_paths = {}
    generated = 0
    cache_hits = 0
    failures = 0

    for decision in decisions:
        for cue in decision.narration_cues:
            cue_key = f"{decision.highlight_id}_{int(cue.at_sec)}"
            voice_id = cue.voice_id or "me_v1"

            try:
                narration = await cache.get_or_generate(
                    text=cue.text,
                    voice_id=voice_id,
                )
                # Copy cached wav to the job's tts dir for easier inspection
                wav_path = tts_dir / f"narration_{cue_key}.wav"
                if str(narration.audio_path) != str(wav_path):
                    import shutil
                    shutil.copy2(narration.audio_path, wav_path)

                state.narration_paths[cue_key] = str(wav_path)

                if narration.used_count > 1:
                    cache_hits += 1
                    logger.debug(f"[E8] Cache hit for cue {cue_key}")
                else:
                    generated += 1
                    logger.info(
                        f"[E8] Generated {narration.duration_sec:.2f}s narration "
                        f"for {cue_key} (voice={voice_id})"
                    )

            except ValueError as exc:
                # Voice profile not registered — fall back to silence
                logger.warning(f"[E8] {exc} — using silent placeholder")
                failures += 1
                wav_path = tts_dir / f"narration_{cue_key}.wav"
                est_dur = max(0.5, len(cue.text) * 0.05)
                _write_silent_wav(wav_path, est_dur)
                state.narration_paths[cue_key] = str(wav_path)

            except Exception as exc:
                # Synthesis error — fall back to silence, don't crash pipeline
                logger.warning(f"[E8] TTS synthesis failed for {cue_key}: {exc}")
                failures += 1
                wav_path = tts_dir / f"narration_{cue_key}.wav"
                est_dur = max(0.5, len(cue.text) * 0.05)
                _write_silent_wav(wav_path, est_dur)
                state.narration_paths[cue_key] = str(wav_path)

    logger.info(
        f"[E8] TTS complete: {generated} generated, {cache_hits} cache hits, "
        f"{failures} fallback(s) | {total_cues} total cues"
    )
