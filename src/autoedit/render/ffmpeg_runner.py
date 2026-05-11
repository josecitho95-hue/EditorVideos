"""FFmpeg runner — execute render commands and parse progress."""

import subprocess
from pathlib import Path

from loguru import logger


def run_ffmpeg(cmd: list[str], timeout: int = 3600) -> Path:
    """Execute an FFmpeg command and return the output path.

    Args:
        cmd: FFmpeg command list (last element should be output path).
        timeout: Max seconds to wait.

    Returns:
        Path to the output file.
    """
    output_path = Path(cmd[-1])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Running FFmpeg: {' '.join(cmd[:10])} ... -> {output_path}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        logger.error(f"FFmpeg stderr: {result.stderr}")
        raise RuntimeError(f"FFmpeg failed with code {result.returncode}: {result.stderr[:500]}")

    logger.info(f"FFmpeg complete: {output_path}")
    return output_path
