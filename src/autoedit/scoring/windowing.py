"""Window extraction from fused scores — peak detection + NMS."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from loguru import logger
from scipy.signal import find_peaks

from autoedit.domain.ids import VodId, WindowId, new_id
from autoedit.domain.signals import WindowCandidate


@dataclass
class WindowingConfig:
    """Configuration for window extraction — used in tests and CLI overrides."""

    window_sec: float = 10.0          # total window duration around peak
    hop_sec: float = 1.0              # (reserved — future sliding-window use)
    min_duration: float = 10.0        # minimum window duration in seconds
    nms_iou_threshold: float = 0.5    # IoU overlap threshold for NMS


def extract_windows(
    fused_scores: np.ndarray,
    normalized: dict[str, np.ndarray] | None = None,
    vod_id: VodId | None = None,
    transcript_text: str = "",
    top_n: int = 20,
    window_radius_sec: float = 25.0,
    min_duration_sec: float = 15.0,
    max_duration_sec: float = 60.0,
    overlap_threshold: float = 0.30,
    config: WindowingConfig | None = None,
) -> list[WindowCandidate]:
    """Extract top-N candidate windows from a per-second fused score array.

    Args:
        fused_scores: 1-D score array, one value per second of the VOD.
            Accepts both ``np.ndarray`` and ``pd.Series``.
        normalized: Per-signal normalised arrays used to populate
            ``score_breakdown``. Optional — defaults to zeros if absent.
        vod_id: VOD identifier for the returned :class:`WindowCandidate` objects.
            Defaults to an empty-string sentinel when not provided (useful in tests).
        transcript_text: Transcript excerpt stored on every window.
        top_n: Maximum number of windows to return.
        window_radius_sec: Half-duration of each window around a detected peak.
        min_duration_sec: Windows shorter than this are padded to this length.
        max_duration_sec: Windows longer than this are truncated.
        overlap_threshold: IoU threshold above which a window is suppressed by NMS.
        config: Optional :class:`WindowingConfig` that overrides the individual
            duration/overlap parameters above.

    Returns:
        List of :class:`WindowCandidate` objects, sorted by score descending,
        with consecutive ``rank`` values starting at 1.
    """
    # Accept pd.Series transparently
    if hasattr(fused_scores, "values"):
        fused_scores = fused_scores.values  # type: ignore[union-attr]

    # Apply WindowingConfig overrides when provided
    if config is not None:
        window_radius_sec = config.window_sec / 2
        min_duration_sec = config.min_duration
        overlap_threshold = config.nms_iou_threshold

    _normalized = normalized or {}
    _vod_id = vod_id if vod_id is not None else VodId("")

    logger.info("Extracting window candidates…")
    n_seconds = len(fused_scores)

    def _signal_at(key: str, idx: int) -> float:
        arr = _normalized.get(key)
        if arr is None or idx >= len(arr):
            return 0.0
        return float(arr[idx])

    # Peak detection — prominence filter removes noise bumps
    peaks, _ = find_peaks(
        fused_scores,
        prominence=0.05,
        distance=int(window_radius_sec),
    )

    if len(peaks) == 0:
        logger.warning("No peaks found — returning empty window list")
        return []

    candidates: list[WindowCandidate] = []
    for peak in peaks:
        start = max(0, int(peak - window_radius_sec))
        end = min(n_seconds, int(peak + window_radius_sec))

        # Enforce min/max duration
        if end - start < min_duration_sec:
            end = min(n_seconds, start + int(min_duration_sec))
        if end - start > max_duration_sec:
            end = start + int(max_duration_sec)

        candidates.append(
            WindowCandidate(
                id=WindowId(new_id()),
                vod_id=_vod_id,
                start_sec=float(start),
                end_sec=float(end),
                score=float(fused_scores[peak]),
                score_breakdown={
                    "audio": _signal_at("audio", peak),
                    "chat": _signal_at("chat", peak),
                    "transcript": _signal_at("transcript", peak),
                    "scene": _signal_at("scene", peak),
                },
                rank=0,
                transcript_excerpt=transcript_text,
            )
        )

    # Sort by score descending before NMS
    candidates.sort(key=lambda w: w.score, reverse=True)

    # Non-Maximum Suppression — remove windows that heavily overlap a higher-scoring one
    filtered: list[WindowCandidate] = []
    for cand in candidates:
        overlap = False
        for kept in filtered:
            inter_start = max(cand.start_sec, kept.start_sec)
            inter_end = min(cand.end_sec, kept.end_sec)
            inter_len = max(0.0, inter_end - inter_start)
            union_len = (
                max(cand.end_sec, kept.end_sec) - min(cand.start_sec, kept.start_sec)
            )
            if union_len > 0 and inter_len / union_len > overlap_threshold:
                overlap = True
                break
        if not overlap:
            filtered.append(cand)
        if len(filtered) >= top_n:
            break

    # Assign consecutive ranks using model_copy — never mutate Pydantic models in-place
    filtered = [w.model_copy(update={"rank": i + 1}) for i, w in enumerate(filtered)]

    logger.info(f"Window extraction complete: {len(filtered)} windows from {len(peaks)} peaks")
    return filtered
