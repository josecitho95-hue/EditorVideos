"""Reframe module — compute crop/scale parameters for format conversion.

Supported output formats
------------------------
* ``youtube``  — 1920×1080  16:9 landscape  (default)
* ``tiktok``   — 1080×1920   9:16 portrait
* ``shorts``   — 1080×1920   9:16 portrait  (alias for tiktok)
* ``square``   — 1080×1080   1:1
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OutputFormat(StrEnum):
    """Canonical output format names accepted by the CLI ``--format`` option."""

    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    SHORTS = "shorts"
    SQUARE = "square"


# Canonical (width, height) for each format
FORMAT_DIMENSIONS: dict[str, tuple[int, int]] = {
    OutputFormat.YOUTUBE: (1920, 1080),
    OutputFormat.TIKTOK: (1080, 1920),
    OutputFormat.SHORTS: (1080, 1920),
    OutputFormat.SQUARE: (1080, 1080),
}


@dataclass
class CropParams:
    """Crop rectangle in source pixels."""

    x: int
    y: int
    w: int
    h: int


def compute_crop(
    input_w: int,
    input_h: int,
    output_w: int,
    output_h: int,
) -> CropParams | None:
    """Compute a centered crop so the input matches the target aspect ratio.

    Returns ``None`` when the input already has (within 1 %) the target ratio —
    meaning only scaling is required, no spatial crop.

    The crop rectangle is always centered and its dimensions are kept even
    (required by most FFmpeg pixel formats).
    """
    target_ratio = output_w / output_h
    input_ratio = input_w / input_h

    if abs(target_ratio - input_ratio) / target_ratio < 0.01:
        return None  # same aspect ratio — just scale

    if target_ratio < input_ratio:
        # Target is narrower → trim left / right columns
        crop_w = int(input_h * output_w / output_h)
        crop_w = (crop_w // 2) * 2  # enforce even
        crop_h = input_h
        crop_x = (input_w - crop_w) // 2
        crop_y = 0
    else:
        # Target is taller → trim top / bottom rows
        crop_h = int(input_w * output_h / output_w)
        crop_h = (crop_h // 2) * 2  # enforce even
        crop_w = input_w
        crop_x = 0
        crop_y = (input_h - crop_h) // 2

    return CropParams(x=crop_x, y=crop_y, w=crop_w, h=crop_h)


def compute_center_crop(input_w: int, input_h: int) -> CropParams:
    """Back-compat helper — 9:16 center crop from any landscape frame."""
    result = compute_crop(input_w, input_h, 1080, 1920)
    if result is None:
        return CropParams(x=0, y=0, w=input_w, h=input_h)
    return result


def compute_smart_crop(
    video_path: str,
    start_sec: float,
    end_sec: float,
    input_w: int,
    input_h: int,
    output_w: int,
    output_h: int,
    sample_interval_sec: float = 2.0,
) -> CropParams | None:
    """Face-detection-aware crop that centers on the subject.

    Samples frames between *start_sec* and *end_sec*, detects faces with
    MediaPipe, applies a Kalman smoother, then computes a static crop
    rectangle centered on the confidence-weighted mean face position.

    Falls back to :func:`compute_crop` (centered) when:
    * The input and output share the same aspect ratio (no crop needed).
    * No faces are detected in any sampled frame.
    * MediaPipe / OpenCV are not installed.

    Parameters
    ----------
    video_path           : absolute path to the source file (used for sampling)
    start_sec / end_sec  : clip time range within the source
    input_w / input_h    : source video dimensions in pixels
    output_w / output_h  : target output dimensions in pixels
    sample_interval_sec  : seconds between sampled frames (default 2 s)

    Returns
    -------
    :class:`CropParams` or ``None`` (same semantics as :func:`compute_crop`).
    """
    from loguru import logger  # local to keep top-level import-free

    # Fast path — same AR, nothing to crop.
    target_ratio = output_w / output_h
    input_ratio = input_w / input_h
    if abs(target_ratio - input_ratio) / target_ratio < 0.01:
        return None

    # Attempt face detection.
    try:
        from autoedit.analysis.vision import (
            aggregate_position,
            sample_face_positions,
            smooth_positions,
        )

        raw = sample_face_positions(
            video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            sample_interval_sec=sample_interval_sec,
        )
        smoothed = smooth_positions(raw)
        centre = aggregate_position(smoothed)
    except Exception as exc:
        logger.warning(f"[reframe] Face detection failed ({exc}); falling back to center crop")
        centre = None

    if centre is None:
        logger.info("[reframe] No faces detected — using center crop")
        return compute_crop(input_w, input_h, output_w, output_h)

    cx_rel, cy_rel = centre
    logger.info(f"[reframe] Smart crop: face centre at ({cx_rel:.2f}, {cy_rel:.2f})")

    # Compute crop dimensions (same geometry as compute_crop).
    if target_ratio < input_ratio:
        # Narrower output (e.g. 9:16) — trim left/right columns.
        crop_w = int(input_h * output_w / output_h)
        crop_w = (crop_w // 2) * 2       # enforce even pixel count
        crop_h = input_h

        ideal_x = int(cx_rel * input_w - crop_w / 2)
        crop_x = max(0, min(ideal_x, input_w - crop_w))
        crop_y = 0
    else:
        # Taller output — trim top/bottom rows.
        crop_h = int(input_w * output_h / output_w)
        crop_h = (crop_h // 2) * 2
        crop_w = input_w

        ideal_y = int(cy_rel * input_h - crop_h / 2)
        crop_y = max(0, min(ideal_y, input_h - crop_h))
        crop_x = 0

    return CropParams(x=crop_x, y=crop_y, w=crop_w, h=crop_h)
