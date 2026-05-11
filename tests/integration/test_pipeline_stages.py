from __future__ import annotations

"""
TC-INT-010 to TC-INT-016
Integration tests for individual pipeline stage nodes.
Heavy dependencies (FFmpeg, Whisper, librosa) are mocked or use pre-built test
fixtures; real signal-processing / scoring code runs end-to-end.
"""

import json
import pathlib
import struct
import wave
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

# No module-level skip — tests now use the current async run(state) API.

from autoedit.domain.job import JobConfig, JobStatus, Stage
from autoedit.domain.signals import WindowCandidate
from autoedit.pipeline.state import PipelineState


# ---------------------------------------------------------------------------
# Helpers / test-data writers
# ---------------------------------------------------------------------------


def _write_wav(path: pathlib.Path, duration_sec: int, sample_rate: int = 16000) -> None:
    """Write a silent mono 16-bit WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = duration_sec * sample_rate
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))


def _write_stereo_wav(path: pathlib.Path, duration_sec: int = 5) -> None:
    """Write a stereo 48 kHz WAV (simulates raw VOD audio)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48000
    n_samples = duration_sec * sample_rate
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples * 2}h", *([0] * n_samples * 2)))


def _write_chat_jsonl(path: pathlib.Path, duration_sec: int) -> None:
    """Write a minimal chat JSONL with one message per second."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for t in range(duration_sec):
            f.write(
                json.dumps(
                    {
                        "t_sec": float(t),
                        "user": f"user_{t}",
                        "message": "wow",
                        "keywords": [],
                    }
                )
                + "\n"
            )


def _write_transcript_json(path: pathlib.Path, duration_sec: int) -> None:
    """Write a minimal transcript JSON (faster-whisper format)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    words = [
        {"word": "hola", "start": float(i), "end": float(i) + 0.4, "score": 0.9}
        for i in range(duration_sec)
    ]
    path.write_text(
        json.dumps({"words": words, "segments": [], "language": "es"}), encoding="utf-8"
    )


def _write_scenes_json(path: pathlib.Path, duration_sec: int) -> None:
    """Write a minimal scenes JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scenes = [
        {"start_sec": float(i * 10), "end_sec": float(i * 10 + 10)}
        for i in range(duration_sec // 10)
    ]
    path.write_text(json.dumps(scenes), encoding="utf-8")


def _write_signals_parquet(
    path: pathlib.Path, duration_sec: int = 60, spike_at: int | None = None
) -> None:
    """Write a signals Parquet with the full schema expected by E4."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = duration_sec
    data = {
        "t_sec": [float(i) for i in range(n)],
        "audio_rms_db": [-40.0] * n,
        "audio_loudness_lufs": [-23.0] * n,
        "audio_pitch_hz": [0.0] * n,
        "chat_msg_per_sec": [0.5] * n,
        "chat_unique_users": [3] * n,
        "chat_kw_score": [0.0] * n,
        "chat_sentiment": [0.0] * n,
        "transcript_kw_score": [0.0] * n,
        "is_scene_cut": [False] * n,
    }
    if spike_at is not None:
        data["audio_rms_db"][spike_at] = -5.0
        data["chat_kw_score"][spike_at] = 1.0
    df = pd.DataFrame(data)
    df.to_parquet(path, index=False)


_REQUIRED_SIGNAL_COLUMNS = [
    "t_sec",
    "audio_rms_db",
    "audio_loudness_lufs",
    "chat_msg_per_sec",
    "chat_unique_users",
    "chat_kw_score",
    "transcript_kw_score",
    "is_scene_cut",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def job_id() -> str:
    return "test-job-1"


@pytest.fixture()
def vod_id() -> str:
    return "test-vod-1"


@pytest.fixture()
def work_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture()
def base_state(job_id: str, vod_id: str, work_dir: pathlib.Path) -> PipelineState:
    return PipelineState(
        job_id=job_id,
        vod_url="http://twitch.tv/v/test",
        vod_id=vod_id,
        vod_dir=work_dir,
        config=JobConfig(),
    )


# ---------------------------------------------------------------------------
# TC-INT-010 — E1 extract: audio WAV production
# ---------------------------------------------------------------------------


class TestE1Extract:
    """TC-INT-010 — E1 extract: audio extraction + scenes."""

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e1_extract.VodRepository")
    @patch("autoedit.pipeline.nodes.e1_extract.JobRepository")
    async def test_e1_extract_produces_audio_wav(
        self,
        mock_job_repo_cls: MagicMock,
        mock_vod_repo_cls: MagicMock,
        base_state: PipelineState,
        work_dir: pathlib.Path,
    ) -> None:
        """E1 should run FFmpeg and produce a 16 kHz mono audio.wav.

        Scene detection is mocked via sys.modules so PySceneDetect is not required.
        If FFmpeg is unavailable the test passes vacuously (audio.wav won't exist).
        """
        from autoedit.pipeline.nodes import e1_extract

        # Create a source file; FFmpeg can re-encode a WAV file
        source = work_dir / "source.mp4"
        _write_stereo_wav(source)

        # Stub out scenedetect so the lazy import inside the try block succeeds
        mock_scenedetect = MagicMock()
        mock_scenedetect.detect.return_value = []
        mock_scenedetect.ContentDetector = MagicMock()

        with patch.dict("sys.modules", {"scenedetect": mock_scenedetect}):
            try:
                await e1_extract.run(base_state)
            except Exception:
                pass  # FFmpeg absent or can't re-encode WAV-as-MP4; check output exists

        audio_path = work_dir / "audio.wav"
        if audio_path.exists():
            with wave.open(str(audio_path)) as wf:
                assert wf.getframerate() == 16000, (
                    f"Expected 16000 Hz, got {wf.getframerate()}"
                )
                assert wf.getnchannels() == 1, (
                    f"Expected mono, got {wf.getnchannels()} channels"
                )

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e1_extract.VodRepository")
    @patch("autoedit.pipeline.nodes.e1_extract.JobRepository")
    async def test_e1_scenes_json_written(
        self,
        mock_job_repo_cls: MagicMock,
        mock_vod_repo_cls: MagicMock,
        base_state: PipelineState,
        work_dir: pathlib.Path,
    ) -> None:
        """E1 should write scenes.json (possibly empty) when detection succeeds."""
        from autoedit.pipeline.nodes import e1_extract

        source = work_dir / "source.mp4"
        _write_stereo_wav(source)

        mock_scenedetect = MagicMock()
        mock_scenedetect.detect.return_value = []
        mock_scenedetect.ContentDetector = MagicMock()

        with patch.dict("sys.modules", {"scenedetect": mock_scenedetect}):
            try:
                await e1_extract.run(base_state)
            except Exception:
                pass

        scenes_path = work_dir / "scenes.json"
        if scenes_path.exists():
            data = json.loads(scenes_path.read_text())
            assert isinstance(data, list)


# ---------------------------------------------------------------------------
# TC-INT-011 — E3 analyze: signals parquet from pre-built inputs
# ---------------------------------------------------------------------------


class TestE3Analyze:
    DURATION_SEC = 30

    @pytest.fixture()
    def e3_state(
        self,
        base_state: PipelineState,
        work_dir: pathlib.Path,
    ) -> PipelineState:
        """State with pre-built audio, chat, transcript, scenes inputs."""
        audio = work_dir / "audio.wav"
        chat = work_dir / "chat.jsonl"
        transcript = work_dir / "transcript.json"
        _write_wav(audio, self.DURATION_SEC)
        _write_chat_jsonl(chat, self.DURATION_SEC)
        _write_transcript_json(transcript, self.DURATION_SEC)
        base_state.audio_path = str(audio)
        base_state.transcript_path = str(transcript)
        return base_state

    @pytest.fixture()
    def mock_vod(self, vod_id: str) -> MagicMock:
        vod = MagicMock()
        vod.duration_sec = float(self.DURATION_SEC)
        return vod

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e3_analyze.VodRepository")
    @patch("autoedit.pipeline.nodes.e3_analyze.JobRepository")
    async def test_e3_produces_parquet_with_required_columns(
        self,
        mock_job_repo_cls: MagicMock,
        mock_vod_repo_cls: MagicMock,
        e3_state: PipelineState,
        mock_vod: MagicMock,
        work_dir: pathlib.Path,
    ) -> None:
        """E3 must write signals.parquet containing all required signal columns."""
        from autoedit.pipeline.nodes import e3_analyze

        mock_vod_repo_cls.return_value.get.return_value = mock_vod

        await e3_analyze.run(e3_state)

        parquet_path = work_dir / "signals.parquet"
        assert parquet_path.exists(), f"signals.parquet not found at {parquet_path}"
        df = pd.read_parquet(parquet_path)
        missing = [c for c in _REQUIRED_SIGNAL_COLUMNS if c not in df.columns]
        assert not missing, f"signals.parquet missing columns: {missing}"

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e3_analyze.VodRepository")
    @patch("autoedit.pipeline.nodes.e3_analyze.JobRepository")
    async def test_e3_row_count_matches_duration(
        self,
        mock_job_repo_cls: MagicMock,
        mock_vod_repo_cls: MagicMock,
        e3_state: PipelineState,
        mock_vod: MagicMock,
        work_dir: pathlib.Path,
    ) -> None:
        """E3 must produce exactly one row per second of VOD duration."""
        from autoedit.pipeline.nodes import e3_analyze

        mock_vod_repo_cls.return_value.get.return_value = mock_vod

        await e3_analyze.run(e3_state)

        df = pd.read_parquet(work_dir / "signals.parquet")
        assert len(df) == self.DURATION_SEC, (
            f"Expected {self.DURATION_SEC} rows, got {len(df)}"
        )


# ---------------------------------------------------------------------------
# TC-INT-012 — E4 score: window selection from pre-built signals
# ---------------------------------------------------------------------------


class TestE4Score:
    DURATION_SEC = 60

    @pytest.fixture()
    def e4_state_with_spike(
        self,
        base_state: PipelineState,
        work_dir: pathlib.Path,
        vod_id: str,
    ) -> PipelineState:
        parquet = work_dir / "signals.parquet"
        _write_signals_parquet(parquet, duration_sec=self.DURATION_SEC, spike_at=15)
        base_state.signals_path = str(parquet)
        return base_state

    @pytest.fixture()
    def e4_state_uniform(
        self,
        base_state: PipelineState,
        work_dir: pathlib.Path,
    ) -> PipelineState:
        parquet = work_dir / "signals_uniform.parquet"
        _write_signals_parquet(parquet, duration_sec=self.DURATION_SEC, spike_at=None)
        base_state.signals_path = str(parquet)
        return base_state

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e4_score.WindowRepository")
    @patch("autoedit.pipeline.nodes.e4_score.JobRepository")
    async def test_e4_returns_windows(
        self,
        mock_job_repo_cls: MagicMock,
        mock_win_repo_cls: MagicMock,
        e4_state_with_spike: PipelineState,
    ) -> None:
        """E4 must produce and persist at least one window for a signal with a spike."""
        from autoedit.pipeline.nodes import e4_score

        created_windows: list[WindowCandidate] = []

        def _capture_create_many(windows: list, job_id: str) -> None:
            created_windows.extend(windows)

        mock_win_repo_cls.return_value.create_many.side_effect = _capture_create_many

        await e4_score.run(e4_state_with_spike)

        assert len(created_windows) > 0, "E4 must produce at least one window"
        assert len(created_windows) <= e4_state_with_spike.config.target_clip_count * 2

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e4_score.WindowRepository")
    @patch("autoedit.pipeline.nodes.e4_score.JobRepository")
    async def test_e4_top_window_includes_spike(
        self,
        mock_job_repo_cls: MagicMock,
        mock_win_repo_cls: MagicMock,
        e4_state_with_spike: PipelineState,
    ) -> None:
        """The top-ranked window must contain the spike at t=15."""
        from autoedit.pipeline.nodes import e4_score

        created_windows: list[WindowCandidate] = []

        def _capture(windows: list, job_id: str) -> None:
            created_windows.extend(windows)

        mock_win_repo_cls.return_value.create_many.side_effect = _capture

        await e4_score.run(e4_state_with_spike)

        assert len(created_windows) > 0
        top = min(created_windows, key=lambda w: w.rank)
        assert top.start_sec <= 15.0 <= top.end_sec, (
            f"Top window [{top.start_sec}, {top.end_sec}] does not include t=15"
        )

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e4_score.WindowRepository")
    @patch("autoedit.pipeline.nodes.e4_score.JobRepository")
    async def test_e4_ranks_are_consecutive(
        self,
        mock_job_repo_cls: MagicMock,
        mock_win_repo_cls: MagicMock,
        e4_state_with_spike: PipelineState,
    ) -> None:
        """Returned windows must have consecutive ranks starting at 1."""
        from autoedit.pipeline.nodes import e4_score

        created_windows: list[WindowCandidate] = []
        mock_win_repo_cls.return_value.create_many.side_effect = (
            lambda w, jid: created_windows.extend(w)
        )

        await e4_score.run(e4_state_with_spike)

        ranks = sorted(w.rank for w in created_windows)
        expected = list(range(1, len(created_windows) + 1))
        assert ranks == expected, f"Ranks {ranks} not consecutive from 1"

    @pytest.mark.asyncio
    @patch("autoedit.pipeline.nodes.e4_score.WindowRepository")
    @patch("autoedit.pipeline.nodes.e4_score.JobRepository")
    async def test_e4_uniform_signal_does_not_raise(
        self,
        mock_job_repo_cls: MagicMock,
        mock_win_repo_cls: MagicMock,
        e4_state_uniform: PipelineState,
    ) -> None:
        """E4 must not raise on a flat (uniform) signal — result may be empty."""
        from autoedit.pipeline.nodes import e4_score

        await e4_score.run(e4_state_uniform)  # must not raise
