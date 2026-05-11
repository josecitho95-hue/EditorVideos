#!/usr/bin/env python3
"""End-to-end pipeline test with a synthetic local video."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from autoedit.domain.ids import JobId, VodId, new_id
from autoedit.domain.job import Job, JobConfig, JobStatus
from autoedit.settings import settings
from autoedit.storage.db import init_db
from autoedit.storage.repositories.jobs import JobRepository


def _create_test_video(path: Path, duration_sec: int = 10) -> None:
    """Create a synthetic 1080p test video with FFmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_sec}:size=1920x1080:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=10",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg test video failed: {result.stderr}")
    print(f"Created test video: {path} ({path.stat().st_size} bytes)")


def _setup_mock_ingest(job_id: str, vod_url: str) -> Path:
    """Manually set up E0 output so we can test E1-E4."""
    vod_id = VodId(new_id())
    vod_dir = settings.data_dir / "vods" / vod_id
    vod_dir.mkdir(parents=True, exist_ok=True)

    source_path = vod_dir / "source.mp4"
    _create_test_video(source_path, duration_sec=10)

    # Create chat file (empty is fine)
    chat_path = vod_dir / "chat.jsonl"
    chat_path.write_text("")

    # Persist VOD metadata
    from autoedit.storage.repositories.vods import VodRepository
    VodRepository().create(
        vod_id=vod_id,
        url=vod_url,
        title="Synthetic test video",
        streamer="autoedit-test",
        duration_sec=10.0,
        recorded_at=datetime.now(UTC).isoformat(),
        language="es",
        source_path=str(source_path),
        source_size_mb=round(source_path.stat().st_size / (1024 * 1024), 2),
    )

    # Update job with vod_id
    JobRepository().update_vod_id(job_id, vod_id)
    JobRepository().update_status(job_id, JobStatus.RUNNING)

    return vod_dir, vod_id


def main() -> int:
    print("=" * 60)
    print("AutoEdit AI — End-to-End Pipeline Test (E0-E8)")
    print("=" * 60)

    # Ensure DB exists
    init_db()

    job_id = JobId(new_id())
    vod_url = f"mock://test/{new_id()}"
    config = JobConfig(
        target_clip_count=2,
        clip_min_duration_sec=5.0,
        clip_max_duration_sec=10.0,
        language="es",
    )

    job = Job(
        id=job_id,
        vod_url=vod_url,
        status=JobStatus.QUEUED,
        config=config,
        created_at=datetime.now(UTC),
    )
    JobRepository().create(job)
    print(f"Job created: {job_id}")

    # Mock E0 (skip actual download)
    print("\n[E0] Setting up synthetic VOD...")
    vod_dir, vod_id = _setup_mock_ingest(job_id, vod_url)
    print(f"[E0] VOD ready: {vod_dir}")

    # Manually create state and run E1-E4
    from autoedit.pipeline.state import PipelineState
    state = PipelineState(
        job_id=job_id,
        vod_url=vod_url,
        vod_id=vod_id,
        config=config,
        vod_dir=vod_dir,
    )

    async def _run() -> None:
        from autoedit.pipeline.nodes import (
            e1_extract,
            e2_transcribe,
            e3_analyze,
            e4_score,
            e5_triage,
            e6_retrieve,
            e7_direct,
            e8_tts,
        )

        print("\n[E1] Extracting audio & scenes...")
        await e1_extract.run(state)
        print(f"[E1] Audio: {state.audio_path}")
        print(f"[E1] Scenes: {state.scenes_path}")

        print("\n[E2] Transcribing audio...")
        await e2_transcribe.run(state)
        print(f"[E2] Transcript: {state.transcript_path}")

        print("\n[E3] Analyzing signals...")
        await e3_analyze.run(state)
        print(f"[E3] Signals: {state.signals_path}")

        print("\n[E4] Scoring & extracting windows...")
        await e4_score.run(state)
        print("[E4] Windows saved to database")

        print("\n[E5] Triaging windows with LLM...")
        # Mock LLM to avoid API costs during test
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "intent": "fail",
            "confidence": 0.92,
            "keep": True,
            "reasoning": "Streamer falls dramatically in the test pattern",
        })
        with patch("autoedit.pipeline.nodes.e5_triage.openrouter.chat", new_callable=AsyncMock, return_value=mock_response):
            await e5_triage.run(state)
        print("[E5] Highlights created")

        print("\n[E6] Retrieving assets...")
        await e6_retrieve.run(state)
        print("[E6] Retrieve complete")

        print("\n[E7] Generating edit decisions...")
        # Mock Director LLM to avoid API costs
        director_mock = MagicMock()
        director_mock.content = json.dumps({
            "title": "Epic Fail Test",
            "trim": {"start_sec": 0.0, "end_sec": 10.0, "reason": "Full test window"},
            "zoom_events": [{"at_sec": 5.0, "duration_sec": 1.0, "kind": "punch_in", "intensity": 1.8}],
            "meme_overlays": [],
            "sfx_cues": [],
            "narration_cues": [{"text": "Se lo veia venir desde el principio.", "at_sec": 3.0, "voice_id": "me_v1", "duck_main_audio_db": -10.0}],
            "subtitle_style": {},
            "rationale": "Test edit decision for synthetic video",
        })
        with patch("autoedit.pipeline.nodes.e7_direct.openrouter.chat", new_callable=AsyncMock, return_value=director_mock):
            await e7_direct.run(state)
        print("[E7] Direct complete")

        print("\n[E8] Generating TTS narration...")
        await e8_tts.run(state)
        print("[E8] TTS complete")

    try:
        asyncio.run(_run())
        JobRepository().update_status(job_id, JobStatus.DONE)
        print(f"\n[OK] Pipeline complete for job {job_id}")

        # Show results
        from autoedit.storage.repositories.windows import WindowRepository
        windows = WindowRepository().list_by_job(job_id)
        print(f"\nGenerated {len(windows)} window(s):")
        for w in windows:
            print(f"  - {w.start_sec:.1f}s–{w.end_sec:.1f}s (score={w.score:.3f})")

        from autoedit.storage.repositories.highlights import HighlightRepository
        highlights = HighlightRepository().list_by_job(job_id, include_discarded=True)
        print(f"\nGenerated {len(highlights)} highlight(s):")
        for h in highlights:
            status = "KEPT" if not h.discarded else "DISCARDED"
            print(f"  - [{status}] {h.intent.value} (confidence={h.triage_confidence:.2f}): {h.triage_reasoning[:60]}...")

        from autoedit.storage.repositories.edit_decisions import EditDecisionRepository
        decisions = EditDecisionRepository().list_by_job(job_id)
        print(f"\nGenerated {len(decisions)} edit decision(s):")
        for d in decisions:
            print(f"  - {d.title}")
            print(f"    Zoom: {len(d.zoom_events)}, Memes: {len(d.meme_overlays)}, SFX: {len(d.sfx_cues)}, Narration: {len(d.narration_cues)}")
            print(f"    Trim: {d.trim.start_sec:.1f}s–{d.trim.end_sec:.1f}s")

        if hasattr(state, "narration_paths") and state.narration_paths:
            print(f"\nGenerated {len(state.narration_paths)} TTS file(s):")
            for k, v in state.narration_paths.items():
                print(f"  - {k}: {v}")

        return 0
    except Exception as exc:
        JobRepository().update_status(job_id, JobStatus.FAILED, error=str(exc))
        print(f"\n[FAIL] Pipeline failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
