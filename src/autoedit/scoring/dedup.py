"""Clip deduplication — IoU-based Non-Maximum Suppression on rendered time ranges.

After E7 generates EditDecisions, multiple decisions can still reference
overlapping time windows (e.g. if NMS in E4 was permissive, or two windows
bracket the same moment from different angles).  This module applies a final
deduplication step *before* FFmpeg is invoked so we never render two clips
that cover essentially the same content.

Algorithm
---------
1. Compute the **absolute** rendered time range for each decision:
   ``abs_start = window_offset + trim.start_sec``
   ``abs_end   = window_offset + trim.end_sec``
2. Sort by triage confidence descending (highest-confidence clip wins).
3. Non-Maximum Suppression: for each candidate, if its rendered range
   overlaps any already-kept clip by IoU ≥ ``iou_threshold``, discard it.
4. Return the surviving list.

Default IoU threshold is **0.40** — two clips sharing more than 40 % of their
combined time span are considered duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class DeduplicationInput:
    """Bundle everything needed to deduplicate a single edit decision.

    Parameters
    ----------
    decision       : :class:`autoedit.domain.edit_decision.EditDecision`
    window_offset  : absolute start (seconds) of the scored window in the source
    confidence     : triage confidence from E5 (higher → more likely to survive)
    """

    decision: Any        # EditDecision — not imported to avoid circular deps
    window_offset: float
    confidence: float

    @property
    def abs_start(self) -> float:
        return self.window_offset + self.decision.trim.start_sec

    @property
    def abs_end(self) -> float:
        return self.window_offset + self.decision.trim.end_sec

    @property
    def duration(self) -> float:
        return max(0.0, self.abs_end - self.abs_start)


def _iou(a: DeduplicationInput, b: DeduplicationInput) -> float:
    """Intersection-over-Union of two time ranges."""
    inter_start = max(a.abs_start, b.abs_start)
    inter_end = min(a.abs_end, b.abs_end)
    inter = max(0.0, inter_end - inter_start)
    union = max(a.abs_end, b.abs_end) - min(a.abs_start, b.abs_start)
    return inter / union if union > 0 else 0.0


def deduplicate_decisions(
    items: list[DeduplicationInput],
    iou_threshold: float = 0.40,
) -> list[DeduplicationInput]:
    """Apply IoU NMS and return surviving decisions.

    The returned list preserves **confidence-descending** order (not original
    order), making it convenient to render the best clips first.

    Parameters
    ----------
    items          : edit decisions to deduplicate
    iou_threshold  : overlap fraction above which a lower-confidence clip is
                     suppressed.  Range (0, 1].  Default ``0.40``.

    Returns
    -------
    Filtered list, sorted by confidence descending.
    """
    if not items:
        return []

    # Sort by confidence descending so the best clip always survives
    sorted_items = sorted(items, key=lambda x: x.confidence, reverse=True)

    kept: list[DeduplicationInput] = []
    for item in sorted_items:
        duplicate = False
        for survivor in kept:
            overlap = _iou(item, survivor)
            if overlap >= iou_threshold:
                logger.info(
                    f"[dedup] Suppressed '{item.decision.title}' "
                    f"({item.abs_start:.1f}s-{item.abs_end:.1f}s, conf={item.confidence:.2f}) "
                    f"IoU={overlap:.2f} with '{survivor.decision.title}'"
                )
                duplicate = True
                break
        if not duplicate:
            kept.append(item)

    logger.info(
        f"[dedup] {len(kept)}/{len(items)} decisions kept "
        f"(threshold IoU={iou_threshold:.2f})"
    )
    return kept
