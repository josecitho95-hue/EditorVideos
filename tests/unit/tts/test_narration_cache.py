"""TC-TTS-001 to TC-TTS-006 — NarrationCache: key derivation, hit/miss, persistence."""

from __future__ import annotations

import pathlib
import struct
import wave
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from autoedit.tts.narration_cache import NarrationCache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_cache_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "narration_cache"


@pytest.fixture()
def isolated_db_engine() -> Engine:
    """Per-test in-memory SQLite — narration rows don't leak between tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture()
def mock_tts_engine() -> Any:
    """Fake TTS engine — writes a 1-second silent WAV, returns None (cache reads WAV duration)."""
    _call_count = [0]

    class _FakeEngine:
        async def generate(self, text: str, voice_id: str, output_path: str) -> None:
            _call_count[0] += 1
            p = pathlib.Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            n_samples = 22050
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))

        @property
        def call_count(self) -> int:
            return _call_count[0]

    return _FakeEngine()


@pytest.fixture()
def cache(
    tmp_cache_dir: pathlib.Path,
    mock_tts_engine: Any,
    isolated_db_engine: Engine,
) -> NarrationCache:
    """NarrationCache pre-wired with an isolated in-memory DB and fake TTS engine."""
    return NarrationCache(
        cache_dir=tmp_cache_dir,
        tts_engine=mock_tts_engine,
        session_factory=lambda: Session(isolated_db_engine),
    )


# ---------------------------------------------------------------------------
# TC-TTS-001 — cache key derivation
# ---------------------------------------------------------------------------


class TestNarrationCacheKey:
    def test_same_inputs_same_key(self, cache: NarrationCache) -> None:
        assert cache.compute_key("hola", "me_v1") == cache.compute_key("hola", "me_v1")

    def test_different_text_different_key(self, cache: NarrationCache) -> None:
        assert cache.compute_key("hola", "me_v1") != cache.compute_key("adios", "me_v1")

    def test_different_voice_different_key(self, cache: NarrationCache) -> None:
        assert cache.compute_key("hola", "me_v1") != cache.compute_key("hola", "me_v2")

    def test_key_is_16_chars(self, cache: NarrationCache) -> None:
        key = cache.compute_key("hola", "me_v1")
        assert len(key) == 16, f"Expected key length 16, got {len(key)}"


# ---------------------------------------------------------------------------
# TC-TTS-002 — cache hit / miss
# ---------------------------------------------------------------------------


class TestNarrationCacheHitMiss:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_engine_once(
        self, cache: NarrationCache, mock_tts_engine: Any
    ) -> None:
        await cache.get_or_generate("primera vez", "me_v1")
        assert mock_tts_engine.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_engine_again(
        self, cache: NarrationCache, mock_tts_engine: Any
    ) -> None:
        await cache.get_or_generate("misma frase", "me_v1")
        await cache.get_or_generate("misma frase", "me_v1")
        assert mock_tts_engine.call_count == 1, (
            f"Engine should be called once; got {mock_tts_engine.call_count}"
        )

    @pytest.mark.asyncio
    async def test_cache_hit_returns_same_id(self, cache: NarrationCache) -> None:
        n1 = await cache.get_or_generate("misma frase", "me_v1")
        n2 = await cache.get_or_generate("misma frase", "me_v1")
        assert n1.id == n2.id

    @pytest.mark.asyncio
    async def test_audio_file_exists_after_generate(self, cache: NarrationCache) -> None:
        narration = await cache.get_or_generate("archivo generado", "me_v1")
        assert pathlib.Path(narration.audio_path).exists(), (
            f"Audio file not found at {narration.audio_path}"
        )

    @pytest.mark.asyncio
    async def test_used_count_increments(self, cache: NarrationCache) -> None:
        for _ in range(3):
            await cache.get_or_generate("repetida", "me_v1")
        row = cache.db_lookup("repetida", "me_v1")
        assert row is not None
        assert row.used_count >= 1


# ---------------------------------------------------------------------------
# TC-TTS-003 — persistence
# ---------------------------------------------------------------------------


class TestNarrationPersistence:
    @pytest.mark.asyncio
    async def test_narration_saved_in_sqlite(self, cache: NarrationCache) -> None:
        await cache.get_or_generate("guardado en db", "me_v1")
        row = cache.db_lookup(text="guardado en db", voice_id="me_v1")
        assert row is not None, "Row not found in SQLite after generation"

    @pytest.mark.asyncio
    async def test_voice_id_saved_correctly(self, cache: NarrationCache) -> None:
        await cache.get_or_generate("voz guardada", "me_v1")
        row = cache.db_lookup(text="voz guardada", voice_id="me_v1")
        assert row is not None
        assert row.voice_id == "me_v1"

    @pytest.mark.asyncio
    async def test_duration_positive(self, cache: NarrationCache) -> None:
        narration = await cache.get_or_generate("duracion positiva", "me_v1")
        assert narration.duration_sec > 0.0, (
            f"Expected duration_sec > 0, got {narration.duration_sec}"
        )
