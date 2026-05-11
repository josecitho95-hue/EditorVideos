"""Transcript signal extraction (keyword spikes)."""

import json
from collections import defaultdict

from loguru import logger

from autoedit.domain.signals import ChatSignal

# Spanish + English keywords commonly used in gaming streams
STREAMER_KEYWORDS = {
    "fail", "clutch", "win", "perder", "ganar", "mierda", "carajo", "wtf",
    "omg", "no way", "imposible", "loco", "insane", "crazy", "bug", "glitch",
    "rage", "tilt", "destroyed", "rekt", "ez", "gg", "clip", "highlight",
}


def analyze_transcript(transcript_path: str, duration_sec: float) -> list[ChatSignal]:
    """Extract transcript keyword spikes per second.

    Returns a list of ChatSignal-like objects for transcript kw score.
    We reuse ChatSignal structure for convenience.
    """
    logger.info(f"Analyzing transcript signals: {transcript_path}")
    with open(transcript_path, encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])

    # Accumulate keyword hits per second
    kw_counts: dict[int, int] = defaultdict(int)
    total_word_counts: dict[int, int] = defaultdict(int)

    for seg in segments:
        for word_info in seg.get("words", []):
            t = int(word_info.get("start", 0))
            word = word_info.get("word", "").lower().strip(".,!?¡¿")
            total_word_counts[t] += 1
            if word in STREAMER_KEYWORDS:
                kw_counts[t] += 1

    n_seconds = int(duration_sec)
    signals: list[ChatSignal] = []

    for t in range(n_seconds):
        total = total_word_counts.get(t, 0)
        kw = kw_counts.get(t, 0)
        score = kw / max(total, 1)
        signals.append(
            ChatSignal(
                t_sec=float(t),
                msg_per_sec=0.0,
                unique_users=0,
                keyword_score=float(score),
            )
        )

    logger.info(f"Transcript signal analysis complete: {len(signals)} seconds")
    return signals
