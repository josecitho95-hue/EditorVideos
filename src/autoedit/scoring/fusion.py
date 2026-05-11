"""Signal fusion — combine per-second audio/chat/transcript/scene signals into a single score."""

from __future__ import annotations

import numpy as np
from loguru import logger

from autoedit.domain.signals import AudioSignal, ChatSignal, SceneSignal

# Default channel weights (must sum to 1.0)
#
# Channels:
#   audio       — loudness / RMS (microphone reaction peaks)
#   chat        — message rate + keyword density
#   laughter    — acoustic laughter probability from audio.py heuristic
#   emote_spike — weighted emote intensity × chat burst spike (from chat.py)
#   transcript  — keyword hits in transcription
#   scene       — scene cut proximity (natural edit points)
DEFAULT_WEIGHTS: dict[str, float] = {
    "audio": 0.25,
    "chat": 0.25,
    "laughter": 0.15,
    "emote_spike": 0.10,
    "transcript": 0.15,
    "scene": 0.10,
}


def _normalize(signal: np.ndarray) -> np.ndarray:
    """Map an arbitrary signal into [0, 1] using z-score → sigmoid.

    Flat signals (std < 1e-9) are returned as all-zeros.
    """
    if signal.std() < 1e-9:
        return np.zeros_like(signal)
    z = (signal - signal.mean()) / (signal.std() + 1e-9)
    z = np.clip(z, -3, 3)
    return 1 / (1 + np.exp(-z))  # sigmoid


def _smooth(arr: np.ndarray, window: int = 5) -> np.ndarray:
    """Apply a uniform rolling mean to smooth transient spikes."""
    kernel = np.ones(window) / window
    return np.convolve(arr, kernel, mode="same")


def fuse_signals(
    audio_signals: list[AudioSignal],
    chat_signals: list[ChatSignal],
    transcript_signals: list[ChatSignal],
    scene_signals: list[SceneSignal],
    weights: dict[str, float] | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Fuse signal channels into a single per-second score array.

    Args:
        audio_signals: One :class:`AudioSignal` per second of the VOD.
        chat_signals: One :class:`ChatSignal` per second.
        transcript_signals: One :class:`ChatSignal` per second (keyword score only).
        scene_signals: One :class:`SceneSignal` per second.
        weights: Optional dict overriding :data:`DEFAULT_WEIGHTS`.
            Keys: ``"audio"``, ``"chat"``, ``"laughter"``, ``"emote_spike"``,
            ``"transcript"``, ``"scene"``.

    Returns:
        Tuple of:
        * ``fused`` — ``np.ndarray`` of shape ``(n_seconds,)`` in ``[0, 1]``.
        * ``normalized`` — dict mapping signal names to their normalised arrays.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    n_seconds = len(audio_signals)

    # Build raw arrays — higher is more interesting for each channel.
    # rms_db is negative dBFS (e.g. -40 = quiet, -5 = loud).
    audio_raw = np.array([a.rms_db for a in audio_signals])

    # Chat: message rate + keyword hits (emote/spike handled as separate channel)
    chat_raw = np.array([
        c.msg_per_sec + c.keyword_score * 3
        for c in chat_signals
    ])

    # Laughter: acoustic probability, already in [0,1]
    laughter_raw = np.array([a.laughter_prob for a in audio_signals])

    # Emote + spike: high when both chat is excited AND emotes are firing
    emote_spike_raw = np.array([
        c.emote_score * 0.5 + c.spike_score * 0.5
        for c in chat_signals
    ])

    transcript_raw = np.array([t.keyword_score for t in transcript_signals])
    scene_raw = np.array([1.0 if s.is_cut else 0.0 for s in scene_signals])

    # Normalise, smooth, fuse
    audio_norm      = _smooth(_normalize(audio_raw))
    chat_norm       = _smooth(_normalize(chat_raw))
    laughter_norm   = _smooth(_normalize(laughter_raw))
    emote_spike_norm = _smooth(_normalize(emote_spike_raw))
    transcript_norm = _smooth(_normalize(transcript_raw))
    scene_norm      = _smooth(_normalize(scene_raw))

    fused: np.ndarray = (
        w["audio"]       * audio_norm
        + w["chat"]        * chat_norm
        + w["laughter"]    * laughter_norm
        + w["emote_spike"] * emote_spike_norm
        + w["transcript"]  * transcript_norm
        + w["scene"]       * scene_norm
    )

    normalized: dict[str, np.ndarray] = {
        "audio":       audio_norm,
        "chat":        chat_norm,
        "laughter":    laughter_norm,
        "emote_spike": emote_spike_norm,
        "transcript":  transcript_norm,
        "scene":       scene_norm,
    }

    logger.info(
        f"[fusion] {n_seconds}s | peak={float(fused.max()):.3f} | "
        f"laughter_peak={float(laughter_raw.max()):.2f} | "
        f"emote_spike_peak={float(emote_spike_raw.max()):.2f}"
    )
    return fused, normalized


def fuse_signals_df(
    df: object,
    weights: dict[str, float] | None = None,
) -> object:
    """DataFrame convenience wrapper — converts analysis columns to domain objects.

    Accepts a ``pandas.DataFrame`` with the columns produced by the analysis nodes:

        ``t_sec``, ``audio_rms_db``, ``audio_loudness_lufs``, ``audio_laughter_prob``,
        ``chat_msg_per_sec``, ``chat_unique_users``, ``chat_kw_score``,
        ``chat_emote_score``, ``chat_spike_score``,
        ``transcript_kw_score``, ``is_scene_cut``

    Columns added in later sprint versions are optional (default 0.0).

    Returns:
        ``pd.Series`` of per-second scores indexed by ``t_sec``.
    """
    import pandas as pd  # lazy import — pandas not always needed

    _df: pd.DataFrame = df  # type: ignore[assignment]
    n = len(_df)

    def _get(col: str, default: float = 0.0) -> "pd.Series":
        return _df[col] if col in _df.columns else pd.Series([default] * n)

    audio_signals = [
        AudioSignal(
            t_sec=float(_df["t_sec"].iloc[i]),
            rms_db=float(_df["audio_rms_db"].iloc[i]),
            loudness_lufs=float(_get("audio_loudness_lufs").iloc[i]),
            laughter_prob=float(_get("audio_laughter_prob").iloc[i]),
        )
        for i in range(n)
    ]
    chat_signals = [
        ChatSignal(
            t_sec=float(_df["t_sec"].iloc[i]),
            msg_per_sec=float(_df["chat_msg_per_sec"].iloc[i]),
            unique_users=int(_df["chat_unique_users"].iloc[i]),
            keyword_score=float(_df["chat_kw_score"].iloc[i]),
            emote_score=float(_get("chat_emote_score").iloc[i]),
            spike_score=float(_get("chat_spike_score").iloc[i]),
        )
        for i in range(n)
    ]
    transcript_signals = [
        ChatSignal(
            t_sec=float(_df["t_sec"].iloc[i]),
            msg_per_sec=0.0,
            unique_users=0,
            keyword_score=float(_get("transcript_kw_score").iloc[i]),
        )
        for i in range(n)
    ]
    scene_signals = [
        SceneSignal(
            t_sec=float(_df["t_sec"].iloc[i]),
            is_cut=bool(_df["is_scene_cut"].iloc[i]),
            shot_id=0,
        )
        for i in range(n)
    ]

    fused, _ = fuse_signals(
        audio_signals, chat_signals, transcript_signals, scene_signals, weights
    )
    return pd.Series(fused, index=_df["t_sec"].values, name="score")
