"""Chat analysis signals."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from loguru import logger

from autoedit.domain.signals import ChatSignal

TWITCH_KEYWORDS = {
    "lul", "lol", "omegalul", "pog", "pogchamp", "monkas", "pepehands",
    "f", "w", "gg", "ez", "clutch", "insane", "poggers", "lmao", "haha",
    "jaja", "xd", "jajaja", "fail", "rip", "banned", "timeout",
}


def analyze_chat(chat_path: str, duration_sec: float) -> list[ChatSignal]:
    """Extract chat signals per second.

    Returns a list of ChatSignal, one per second.
    """
    logger.info(f"Analyzing chat: {chat_path}")
    path = Path(chat_path)
    if not path.exists():
        logger.warning("Chat file not found, returning zeros")
        return [
            ChatSignal(t_sec=float(t), msg_per_sec=0.0, unique_users=0, keyword_score=0.0)
            for t in range(int(duration_sec))
        ]

    # Bin messages by second
    bins: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                msg = json.loads(line)
                ts = int(msg.get("ts", 0))
                bins[ts].append(msg)
            except (json.JSONDecodeError, TypeError):
                continue

    n_seconds = int(duration_sec)
    signals: list[ChatSignal] = []

    for t in range(n_seconds):
        msgs = bins.get(t, [])
        users = {m.get("user", "unknown") for m in msgs}
        msgs_text = [m.get("msg", "").lower() for m in msgs]

        # Keyword score: proportion of messages containing keywords
        kw_count = sum(
            1 for text in msgs_text
            if any(kw in text for kw in TWITCH_KEYWORDS)
        )
        keyword_score = kw_count / max(len(msgs), 1)

        # Simple sentiment heuristic
        positive = sum(1 for text in msgs_text if any(w in text for w in {"gg", "wp", "clutch", "pog", "w"}))
        negative = sum(1 for text in msgs_text if any(w in text for w in {"fail", "rip", "f", "bad"}))
        sentiment = (positive - negative) / max(len(msgs), 1)
        sentiment = max(-1.0, min(1.0, sentiment))

        signals.append(
            ChatSignal(
                t_sec=float(t),
                msg_per_sec=float(len(msgs)),
                unique_users=len(users),
                keyword_score=float(keyword_score),
                sentiment=float(sentiment),
            )
        )

    logger.info(f"Chat analysis complete: {len(signals)} seconds")
    return signals
