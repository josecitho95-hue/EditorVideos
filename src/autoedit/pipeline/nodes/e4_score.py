"""E4 Score node: fuse signals and extract windows."""

import json

import pyarrow.parquet as pq
from loguru import logger

from autoedit.domain.ids import VodId
from autoedit.domain.job import JobStatus, Stage
from autoedit.pipeline.state import PipelineState
from autoedit.scoring.fusion import fuse_signals
from autoedit.scoring.windowing import extract_windows
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.windows import WindowRepository


async def run(state: PipelineState) -> None:
    """Execute E4 Score."""
    logger.info(f"[E4] Starting scoring for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.SCORE)

    if not state.signals_path:
        raise RuntimeError("Signals not computed")

    table = pq.read_table(state.signals_path)  # type: ignore[no-untyped-call]

    # Reconstruct signal objects from parquet
    from autoedit.domain.signals import AudioSignal, ChatSignal, SceneSignal

    n_rows = table.num_rows
    audio_signals = [
        AudioSignal(
            t_sec=table.column("t_sec")[i].as_py(),
            rms_db=table.column("audio_rms_db")[i].as_py(),
            loudness_lufs=table.column("audio_loudness_lufs")[i].as_py(),
            pitch_hz=table.column("audio_pitch_hz")[i].as_py() or None,
        )
        for i in range(n_rows)
    ]
    chat_signals = [
        ChatSignal(
            t_sec=table.column("t_sec")[i].as_py(),
            msg_per_sec=table.column("chat_msg_per_sec")[i].as_py(),
            unique_users=table.column("chat_unique_users")[i].as_py(),
            keyword_score=table.column("chat_kw_score")[i].as_py(),
            sentiment=table.column("chat_sentiment")[i].as_py(),
        )
        for i in range(n_rows)
    ]
    transcript_signals = [
        ChatSignal(
            t_sec=table.column("t_sec")[i].as_py(),
            msg_per_sec=0.0,
            unique_users=0,
            keyword_score=table.column("transcript_kw_score")[i].as_py(),
        )
        for i in range(n_rows)
    ]
    scene_signals = [
        SceneSignal(
            t_sec=table.column("t_sec")[i].as_py(),
            is_cut=table.column("is_scene_cut")[i].as_py(),
            shot_id=0,
        )
        for i in range(n_rows)
    ]

    fused, normalized = fuse_signals(audio_signals, chat_signals, transcript_signals, scene_signals)

    # Load all transcript segments for per-window excerpt assignment
    all_segments: list[dict] = []
    if state.transcript_path:
        with open(state.transcript_path, encoding="utf-8") as f:
            data = json.load(f)
            all_segments = data.get("segments", [])

    windows = extract_windows(
        fused_scores=fused,
        normalized=normalized,
        vod_id=VodId(state.vod_id) if state.vod_id else VodId(""),
        transcript_text="",  # will be set per-window below
        top_n=state.config.target_clip_count * 2,
        min_duration_sec=state.config.clip_min_duration_sec,
        max_duration_sec=state.config.clip_max_duration_sec,
    )

    # Assign transcript excerpt per window from segments in [start_sec, end_sec]
    if all_segments:
        updated: list = []
        for w in windows:
            seg_texts = [
                s.get("text", "").strip()
                for s in all_segments
                if w.start_sec <= s.get("start", 0.0) <= w.end_sec
            ]
            excerpt = " ".join(seg_texts)[:500]
            updated.append(w.model_copy(update={"transcript_excerpt": excerpt}))
        windows = updated

    WindowRepository().create_many(windows, state.job_id)

    logger.info(f"[E4] Scoring complete: {len(windows)} windows saved")


# Alias for backward compatibility with legacy tests
def run_e4_score(**kwargs: object) -> None:
    raise NotImplementedError("run_e4_score legacy API removed — use run(state) async")
