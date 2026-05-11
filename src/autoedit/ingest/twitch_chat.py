"""Twitch chat download using chat-downloader."""

import json
from pathlib import Path

from chat_downloader import ChatDownloader
from loguru import logger


def download_chat(vod_url: str, output_path: Path) -> int:
    """Download Twitch chat to a JSONL file.

    Returns the number of messages written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chat_downloader = ChatDownloader()
    chat = chat_downloader.get_chat(vod_url)

    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for msg in chat:
            record = {
                "ts": msg.get("time_in_seconds"),
                "user": msg.get("author", {}).get("name", "unknown"),
                "msg": msg.get("message", ""),
                "emotes": [e.get("name") for e in msg.get("emotes", []) if e.get("name")],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    logger.info(f"Chat download complete: {count} messages -> {output_path}")
    return count
