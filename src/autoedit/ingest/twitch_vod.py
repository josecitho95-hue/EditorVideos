"""Twitch VOD download using yt-dlp."""

import json
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger


def download_vod(vod_url: str, output_dir: Path) -> dict[str, Any]:
    """Download a Twitch VOD using yt-dlp.

    Returns the parsed info json from yt-dlp.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "source.%(ext)s")

    logger.info(f"Starting VOD download: {vod_url}")
    cmd = [
        "yt-dlp",
        "--format", "best[ext=mp4]/best",
        "--output", output_template,
        "--no-progress",
        "--print-json",
    ]
    # Use android client for YouTube to avoid bot verification
    if "youtube.com" in vod_url or "youtu.be" in vod_url:
        cmd.extend(["--extractor-args", "youtube:player_client=android"])
    cmd.append(vod_url)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=3600,
    )

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    # The last line of stdout should be the JSON info
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError("yt-dlp produced no output")

    info: dict[str, Any] = json.loads(lines[-1])
    logger.info(f"VOD download complete: {info.get('id')} — {info.get('title')}")
    return info
