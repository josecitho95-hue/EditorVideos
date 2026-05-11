"""TTS narration cache — SHA256-keyed lookup with SQLite persistence.

Cache key: ``SHA256(voice_id + ":" + text)[:32]`` stored as the primary key
in the ``narrations`` SQLite table. This gives O(1) lookups and automatic
deduplication for identical (text, voice_id) pairs.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlmodel import Session

from autoedit.storage.db import NarrationModel, get_session


def _wav_duration(path: Path) -> float:
    """Read duration in seconds from a WAV file header. Returns 1.0 on error."""
    import wave
    try:
        with wave.open(str(path)) as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 1.0


@dataclass
class Narration:
    """Result of a TTS synthesis (cached or freshly generated)."""

    id: str           # SHA256 cache key (also SQLite PK)
    audio_path: str   # absolute path to the generated .wav file
    duration_sec: float
    used_count: int
    voice_id: str = ""   # voice identifier used for synthesis


class NarrationCache:
    """Content-addressable cache for TTS narration audio.

    Usage::

        cache = NarrationCache(cache_dir=Path("data/narrations"), tts_engine=engine)
        narration = await cache.get_or_generate("Increíble jugada!", "me_v1")
        # narration.audio_path → ready-to-use WAV file

    The TTS engine must expose one of:
    - ``synthesize_async(text, voice_id, output_path) -> float`` (async)
    - ``synthesize(text, voice_id, output_path) -> float`` (sync)

    Both return ``duration_sec`` of the generated audio.
    """

    def __init__(
        self,
        cache_dir: Path,
        tts_engine: object,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._tts = tts_engine
        # Allows tests to inject an isolated in-memory session factory
        self._session_factory: Callable[[], Session] = session_factory or get_session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_key(self, text: str, voice_id: str) -> str:
        """Return the 16-char hex SHA256 cache key for *(text, voice_id)*."""
        payload = f"{voice_id}:{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def db_lookup(self, text: str, voice_id: str) -> Narration | None:
        """Return a cached :class:`Narration` if it exists, or ``None`` on miss."""
        key = self.compute_key(text, voice_id)
        try:
            with self._session_factory() as session:
                row = session.get(NarrationModel, key)
                if row is None:
                    return None
                return Narration(
                    id=row.id,
                    audio_path=row.audio_path,
                    duration_sec=row.duration_sec,
                    used_count=row.used_count,
                    voice_id=row.voice_id,
                )
        except Exception as exc:
            logger.warning(f"[NarrationCache] DB lookup failed: {exc}")
            return None

    async def get_or_generate(self, text: str, voice_id: str) -> Narration:
        """Return cached narration or synthesise a new one.

        1. Checks SQLite cache (O(1) primary-key lookup).
        2. On miss: calls the TTS engine, writes the WAV, persists the record.
        3. Increments ``used_count`` on cache hits.
        """
        cached = self.db_lookup(text, voice_id)
        if cached is not None:
            logger.debug(
                f"[NarrationCache] HIT key={cached.id[:8]}… "
                f"voice={voice_id} used_count={cached.used_count}"
            )
            self._increment_use_count(cached.id)
            return cached

        logger.info(
            f"[NarrationCache] MISS — synthesising {len(text)} chars, voice={voice_id}"
        )
        key = self.compute_key(text, voice_id)
        audio_path = self._cache_dir / f"{key}.wav"

        # Dispatch to TTS engine — check several method name conventions:
        #   synthesize_async / synthesize  (primary protocol)
        #   generate_async / generate      (alternate naming used in some engines)
        synthesize = (
            getattr(self._tts, "synthesize_async", None)
            or getattr(self._tts, "generate_async", None)
            or getattr(self._tts, "synthesize", None)
            or getattr(self._tts, "generate", None)
        )
        if synthesize is None:
            raise AttributeError(
                f"TTS engine {type(self._tts).__name__!r} must implement "
                "synthesize(text, voice_id, output_path) -> float|None "
                "or one of: synthesize_async, generate, generate_async."
            )

        if inspect.iscoroutinefunction(synthesize):
            result = await synthesize(text, voice_id, str(audio_path))
        else:
            result = synthesize(text, voice_id, str(audio_path))

        # Engine may return duration (float) or None (WAV already written to disk)
        if result is None:
            duration_sec = _wav_duration(audio_path)
        else:
            duration_sec = float(result)

        narration = Narration(
            id=key,
            audio_path=str(audio_path),
            duration_sec=float(duration_sec),
            used_count=1,
        )
        self._persist(narration, text, voice_id)
        return narration

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist(self, narration: Narration, text: str, voice_id: str) -> None:
        """Write a freshly generated narration record to SQLite."""
        try:
            with self._session_factory() as session:
                if session.get(NarrationModel, narration.id) is not None:
                    return  # concurrent write already inserted it

                row = NarrationModel(
                    id=narration.id,
                    text=text,
                    voice_id=voice_id,
                    audio_path=narration.audio_path,
                    duration_sec=narration.duration_sec,
                    sample_rate_hz=24000,
                    model="f5-tts",
                    generated_at=datetime.now(tz=timezone.utc).isoformat(),
                    used_count=1,
                )
                session.add(row)
                session.commit()
                logger.debug(f"[NarrationCache] Persisted narration {narration.id[:8]}…")
        except Exception as exc:
            logger.warning(f"[NarrationCache] Failed to persist narration: {exc}")

    def _increment_use_count(self, narration_id: str) -> None:
        """Increment the ``used_count`` column for a cache hit."""
        try:
            with self._session_factory() as session:
                row = session.get(NarrationModel, narration_id)
                if row is not None:
                    row.used_count += 1
                    session.add(row)
                    session.commit()
        except Exception as exc:
            logger.debug(f"[NarrationCache] Could not increment use count: {exc}")
