"""Chat analysis signals — density, emote scoring, and spike detection.

Reads the ``chat.jsonl`` produced by :mod:`autoedit.ingest.twitch_chat` and
converts it to a per-second signal suitable for the E3/E4 pipeline.

Emote scoring
-------------
Every message may contain zero or more emote objects in the ``emotes`` list
field.  Each emote name is looked up in :data:`EMOTE_WEIGHTS`; unknown emotes
score 1.  The per-second *emote_score* is the sum of weighted emotes in that
second, then normalised so that "chat going crazy" maps to ~1.

Spike detection
---------------
A *spike_score* captures how much this second stands out against the recent
baseline (30-second rolling mean).  It is computed as::

    spike_score[t] = msg_per_sec[t] / (rolling_mean[t-30:t] + 1)

clamped to [0, 1] after z-score normalisation.  This means a quiet stream
with one sudden burst scores higher than a consistently busy stream.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from autoedit.domain.signals import ChatSignal

# ---------------------------------------------------------------------------
# Emote weight table
# High-hype (5) → reaction/filler (1).
# Covers global Twitch emotes + common BTTV / 7TV emotes.
# ---------------------------------------------------------------------------

EMOTE_WEIGHTS: dict[str, int] = {
    # Tier 5 — absolute hype
    "OMEGALUL": 5, "OMEGADANCE": 5, "GIGACHAD": 5, "NODDERS": 5,
    # Tier 4 — big hype
    "KEKW": 4, "KEKL": 4, "monkaGIGA": 4, "PogU": 4, "peepoClap": 4,
    "LULW": 4, "PogO": 4, "PauseChamp": 4, "BASED": 4,
    # Tier 3 — standard hype / reaction
    "LUL": 3, "Pog": 3, "PogChamp": 3, "POGGERS": 3, "PogBones": 3,
    "monkaS": 3, "AYAYA": 3, "catJAM": 3, "peepoHappy": 3, "PepeLaugh": 3,
    "HYPE": 3, "Jebaited": 3, "PogChamp": 3, "HYPERS": 3,
    # Tier 2 — reaction / acknowledgement
    "F": 2, "EZ": 2, "Clap": 2, "FeelsBadMan": 2, "FeelsGoodMan": 2,
    "Sadge": 2, "sadge": 2, "WeirdChamp": 2, "5Head": 2, "clueless": 2,
    "COCKA": 2, "LETSGO": 2, "GG": 2, "RIP": 2, "pepega": 2,
    # Tier 1 — filler / low-signal (everything else defaults to 1 anyway)
    "LUL": 1,
}

# Spanish-language keyword set (Twitch streams in Spanish)
TWITCH_KEYWORDS_ES: set[str] = {
    "lul", "lol", "omegalul", "pog", "pogchamp", "monkas",
    "pepehands", "f", "w", "gg", "ez", "clutch", "insane",
    "poggers", "lmao", "haha", "jaja", "xd", "jajaja", "fail",
    "rip", "banned", "timeout", "kekw", "jajajaja", "lmao",
    "no puede ser", "increible", "wtf", "dios", "crack",
}

_ROLLING_WINDOW = 30   # seconds for baseline rolling mean


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_chat(chat_path: str, duration_sec: float) -> list[ChatSignal]:
    """Parse ``chat.jsonl`` and return one :class:`ChatSignal` per second.

    Falls back to all-zero signals when the file is missing (e.g. local VODs
    or Twitch VODs where chat download failed).
    """
    path = Path(chat_path)
    if not path.exists():
        logger.info(f"[chat] No chat file at {chat_path} — using zero signals")
        return _zero_signals(int(duration_sec))

    logger.info(f"[chat] Analyzing {path}")

    # ------------------------------------------------------------------
    # 1. Parse JSONL → bin messages by second
    # ------------------------------------------------------------------
    bins: dict[int, list[dict[str, Any]]] = defaultdict(list)
    total = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                ts = int(msg.get("ts") or 0)
                bins[ts].append(msg)
                total += 1
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    if total == 0:
        logger.warning("[chat] Chat file is empty — using zero signals")
        return _zero_signals(int(duration_sec))

    logger.info(f"[chat] Loaded {total} messages across {len(bins)} seconds")

    n_seconds = int(duration_sec)

    # ------------------------------------------------------------------
    # 2. Per-second raw metrics
    # ------------------------------------------------------------------
    msg_counts   = np.zeros(n_seconds, dtype=float)
    user_counts  = np.zeros(n_seconds, dtype=float)
    kw_scores    = np.zeros(n_seconds, dtype=float)
    emote_scores = np.zeros(n_seconds, dtype=float)
    sentiments   = np.zeros(n_seconds, dtype=float)

    for t in range(n_seconds):
        msgs = bins.get(t, [])
        if not msgs:
            continue

        users = {m.get("user", "?") for m in msgs}
        msg_texts = [m.get("msg", "").lower() for m in msgs]

        # Keyword score (text-based)
        kw_hit = sum(
            1 for text in msg_texts
            if any(kw in text for kw in TWITCH_KEYWORDS_ES)
        )
        kw_scores[t] = kw_hit / len(msgs)

        # Emote score (use the pre-parsed emotes list when available)
        emote_sum = 0.0
        for m in msgs:
            emotes = m.get("emotes") or []
            if emotes:
                for e in emotes:
                    emote_sum += EMOTE_WEIGHTS.get(str(e), 1)
            else:
                # Fallback: scan message text for known emote names
                text = m.get("msg", "")
                for ename, weight in EMOTE_WEIGHTS.items():
                    if ename in text:
                        emote_sum += weight
                        break  # count once per message
        emote_scores[t] = emote_sum

        # Sentiment
        pos = sum(1 for tx in msg_texts if any(w in tx for w in
                  {"gg", "wp", "clutch", "pog", "w", "letsgo", "crack"}))
        neg = sum(1 for tx in msg_texts if any(w in tx for w in
                  {"fail", "rip", "f", "bad", "pobre", "oof"}))
        sentiments[t] = max(-1.0, min(1.0, (pos - neg) / len(msgs)))

        msg_counts[t]  = float(len(msgs))
        user_counts[t] = float(len(users))

    # ------------------------------------------------------------------
    # 3. Spike detection: how far above the rolling baseline is each second?
    # spike_score[t] = msg_counts[t] / (rolling_mean of past 30s + 1)
    # ------------------------------------------------------------------
    rolling_baseline = _rolling_mean(msg_counts, _ROLLING_WINDOW)
    raw_spike = msg_counts / (rolling_baseline + 1.0)
    spike_scores = _zscore_clamp(raw_spike)   # → [0, 1]

    # Normalise emote_scores to [0, 1] across the whole session
    if emote_scores.max() > 0:
        emote_norm = emote_scores / emote_scores.max()
    else:
        emote_norm = emote_scores

    # ------------------------------------------------------------------
    # 4. Build ChatSignal list
    # ------------------------------------------------------------------
    signals: list[ChatSignal] = []
    for t in range(n_seconds):
        signals.append(ChatSignal(
            t_sec=float(t),
            msg_per_sec=float(msg_counts[t]),
            unique_users=int(user_counts[t]),
            keyword_score=float(kw_scores[t]),
            emote_score=float(emote_norm[t]),
            spike_score=float(spike_scores[t]),
            sentiment=float(sentiments[t]),
        ))

    logger.info(
        f"[chat] Analysis complete: {n_seconds}s | "
        f"peak msg/s={msg_counts.max():.1f} | "
        f"peak emote={emote_scores.max():.1f} | "
        f"peak spike={raw_spike.max():.1f}x"
    )
    return signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_signals(n_seconds: int) -> list[ChatSignal]:
    return [
        ChatSignal(
            t_sec=float(t),
            msg_per_sec=0.0, unique_users=0,
            keyword_score=0.0, emote_score=0.0,
            spike_score=0.0, sentiment=0.0,
        )
        for t in range(n_seconds)
    ]


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Past-only rolling mean (causal — no look-ahead)."""
    result = np.zeros_like(arr)
    for i in range(len(arr)):
        start = max(0, i - window)
        result[i] = arr[start:i].mean() if i > 0 else 0.0
    return result


def _zscore_clamp(arr: np.ndarray) -> np.ndarray:
    """Z-score normalise then pass through sigmoid → [0, 1]."""
    std = arr.std()
    if std < 1e-9:
        return np.zeros_like(arr)
    z = (arr - arr.mean()) / (std + 1e-9)
    z = np.clip(z, -3, 3)
    return 1.0 / (1.0 + np.exp(-z))
