"""E3 Analyze node: compute all signals."""


import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

from autoedit.analysis.audio import analyze_audio
from autoedit.analysis.chat import analyze_chat
from autoedit.analysis.scenes import detect_scenes
from autoedit.analysis.transcript_signals import analyze_transcript
from autoedit.domain.job import JobStatus, Stage
from autoedit.domain.signals import AudioSignal, ChatSignal, SceneSignal
from autoedit.pipeline.state import PipelineState
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.vods import VodRepository


async def run(state: PipelineState) -> None:
    """Execute E3 Analyze."""
    logger.info(f"[E3] Starting analysis for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.ANALYZE)

    if not state.vod_dir or not state.vod_id:
        raise RuntimeError("VOD not ready for analysis")

    signals_path = state.vod_dir / "signals.parquet"

    # --- Idempotency: skip heavy analysis if signals already exist ---
    if signals_path.exists():
        logger.info(f"[E3] Skipping — signals.parquet already exists ({signals_path})")
        state.signals_path = str(signals_path)
        return

    vod = VodRepository().get(state.vod_id)
    if not vod:
        raise RuntimeError("VOD not found in database")

    duration_sec = vod.duration_sec

    # Run analyses
    audio_signals = analyze_audio(state.audio_path) if state.audio_path else []
    chat_signals = analyze_chat(str(state.vod_dir / "chat.jsonl"), duration_sec)
    scene_signals = detect_scenes(str(state.vod_dir / "source.mp4"), duration_sec)
    transcript_signals = analyze_transcript(state.transcript_path, duration_sec) if state.transcript_path else []

    # Pad shorter signals to match duration
    n_seconds = int(duration_sec)

    from collections.abc import Callable
    from typing import TypeVar
    T = TypeVar("T")
    def pad(sigs: list[T], factory: Callable[[int], T]) -> list[T]:
        while len(sigs) < n_seconds:
            sigs.append(factory(len(sigs)))
        return sigs[:n_seconds]

    if not audio_signals:
        audio_signals = [AudioSignal(t_sec=float(t), rms_db=-60.0, loudness_lufs=-70.0) for t in range(n_seconds)]
    if not chat_signals:
        chat_signals = [ChatSignal(t_sec=float(t), msg_per_sec=0.0, unique_users=0, keyword_score=0.0) for t in range(n_seconds)]
    if not transcript_signals:
        transcript_signals = [ChatSignal(t_sec=float(t), msg_per_sec=0.0, unique_users=0, keyword_score=0.0) for t in range(n_seconds)]
    if not scene_signals:
        scene_signals = [SceneSignal(t_sec=float(t), is_cut=False, shot_id=0) for t in range(n_seconds)]

    audio_signals = pad(audio_signals, lambda t: AudioSignal(t_sec=float(t), rms_db=-60.0, loudness_lufs=-70.0))
    chat_signals = pad(chat_signals, lambda t: ChatSignal(t_sec=float(t), msg_per_sec=0.0, unique_users=0, keyword_score=0.0))
    transcript_signals = pad(transcript_signals, lambda t: ChatSignal(t_sec=float(t), msg_per_sec=0.0, unique_users=0, keyword_score=0.0))
    scene_signals = pad(scene_signals, lambda t: SceneSignal(t_sec=float(t), is_cut=False, shot_id=0))

    # Build parquet table
    table = pa.table({
        "t_sec": [float(t) for t in range(n_seconds)],
        # Audio
        "audio_rms_db": [a.rms_db for a in audio_signals],
        "audio_loudness_lufs": [a.loudness_lufs for a in audio_signals],
        "audio_pitch_hz": [a.pitch_hz or 0.0 for a in audio_signals],
        "audio_laughter_prob": [a.laughter_prob for a in audio_signals],
        # Chat
        "chat_msg_per_sec": [c.msg_per_sec for c in chat_signals],
        "chat_unique_users": [c.unique_users for c in chat_signals],
        "chat_kw_score": [c.keyword_score for c in chat_signals],
        "chat_emote_score": [c.emote_score for c in chat_signals],
        "chat_spike_score": [c.spike_score for c in chat_signals],
        "chat_sentiment": [c.sentiment for c in chat_signals],
        # Transcript
        "transcript_kw_score": [t.keyword_score for t in transcript_signals],
        # Scenes
        "is_scene_cut": [s.is_cut for s in scene_signals],
    })

    signals_path = state.vod_dir / "signals.parquet"
    pq.write_table(table, signals_path)  # type: ignore[no-untyped-call]
    state.signals_path = str(signals_path)

    logger.info(f"[E3] Analysis complete: {n_seconds} seconds -> {signals_path}")


# Alias for backward compatibility with legacy tests
def run_e3_analyze(**kwargs: object) -> None:
    raise NotImplementedError("run_e3_analyze legacy API removed — use run(state) async")
