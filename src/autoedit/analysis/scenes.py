"""Scene detection using PySceneDetect."""

from pathlib import Path

from loguru import logger
from scenedetect import ContentDetector, detect

from autoedit.domain.signals import SceneSignal


def detect_scenes(video_path: str, duration_sec: float) -> list[SceneSignal]:
    """Detect scene cuts in a video.

    Returns a list of SceneSignal, one per second.
    """
    logger.info(f"Detecting scenes: {video_path}")
    path = Path(video_path)
    if not path.exists():
        logger.warning("Video not found, returning no cuts")
        return [
            SceneSignal(t_sec=float(t), is_cut=False, shot_id=0)
            for t in range(int(duration_sec))
        ]

    scenes = detect(str(path), ContentDetector(threshold=27.0))

    cut_seconds = {int(scene[0].get_seconds()) for scene in scenes}

    n_seconds = int(duration_sec)
    signals: list[SceneSignal] = []
    shot_id = 0

    for t in range(n_seconds):
        if t in cut_seconds:
            shot_id += 1
        signals.append(
            SceneSignal(t_sec=float(t), is_cut=(t in cut_seconds), shot_id=shot_id)
        )

    logger.info(f"Scene detection complete: {len(cut_seconds)} cuts, {shot_id} shots")
    return signals
