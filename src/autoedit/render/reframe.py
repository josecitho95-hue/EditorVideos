"""Reframe module — compute crop/scale parameters for format conversion.

Supported output formats
------------------------
* ``youtube``  — 1920×1080  16:9 landscape  (default)
* ``tiktok``   — 1080×1920   9:16 portrait
* ``shorts``   — 1080×1920   9:16 portrait  (alias for tiktok)
* ``square``   — 1080×1080   1:1

Supported layout modes
----------------------
* ``crop``   — single stream, smart/center crop to output AR (default)
* ``split``  — vertical split: gameplay on top (60 %), face close-up on bottom (40 %)

Split-screen geometry
---------------------
For a 1080×1920 output::

    ┌─────────────────┐  ▲ top_h  (60 % of output_h)
    │   GAMEPLAY      │  │  crop=AR-matched from full source, centered
    │   (top 60 %)   │  │
    └─────────────────┘  ▼
    ┌─────────────────┐  ▲ bot_h  (40 % of output_h)
    │  FACE CLOSE-UP  │  │  40 % of source height around detected face
    │  (bottom 40 %)  │  │
    └─────────────────┘  ▼

Both sections are taken from the *same* source segment so the audio track is
always in sync.  The face crop is centered on the position returned by
:func:`autoedit.analysis.vision.aggregate_position`; if face detection fails
it falls back to the vertical centre of the frame.
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


@dataclass
class SplitLayout:
    """Two-section split-screen layout for portrait output (e.g. TikTok 1080×1920).

    Both crops are taken from the same source video — no secondary camera needed.

    Attributes
    ----------
    game_crop   : crop rectangle for the top (gameplay) section
    face_crop   : crop rectangle for the bottom (face close-up) section
    top_h       : height of the top section in the output frame (px)
    bot_h       : height of the bottom section in the output frame (px)
    output_w    : output frame width (px), same for both sections
    """

    game_crop: CropParams
    face_crop: CropParams
    top_h: int
    bot_h: int
    output_w: int = 1080


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


def compute_split_layout(
    video_path: str,
    start_sec: float,
    end_sec: float,
    input_w: int = 1920,
    input_h: int = 1080,
    output_w: int = 1080,
    output_h: int = 1920,
    top_ratio: float = 0.60,
    face_src_ratio: float = 0.40,
    sample_interval_sec: float = 2.0,
) -> SplitLayout:
    """Compute a vertical split-screen layout from a single source video.

    The source is split into:

    * **Top section** (``top_ratio`` of output height) — gameplay, cropped to the
      correct AR using a center crop.
    * **Bottom section** (remaining height) — face/reaction close-up, centered on
      the face detected in the clip.  The crop covers ``face_src_ratio`` of the
      source frame height so the face appears zoomed-in.

    Parameters
    ----------
    video_path           : absolute path to the source file
    start_sec / end_sec  : clip time range (used for face detection sampling)
    input_w / input_h    : source video dimensions
    output_w / output_h  : final portrait output dimensions (e.g. 1080×1920)
    top_ratio            : fraction of output_h allocated to the game section (0.6)
    face_src_ratio       : fraction of source height used for the face crop (0.4)
    sample_interval_sec  : seconds between sampled frames for face detection

    Returns
    -------
    :class:`SplitLayout`
    """
    from loguru import logger

    # Section heights — kept even for yuv420p compatibility
    top_h = int(output_h * top_ratio) // 2 * 2
    bot_h = output_h - top_h  # already even because output_h is even

    # ------------------------------------------------------------------
    # Game (top) section — center crop to match top section AR
    # AR_top = output_w / top_h  (e.g. 1080/1152 ≈ 0.9375 for 60 % split)
    # Source AR = input_w / input_h = 1.778  → source is wider → crop L/R
    # ------------------------------------------------------------------
    game_crop_w = int(input_h * output_w / top_h) // 2 * 2
    game_crop_w = min(game_crop_w, input_w)           # can't exceed source width
    game_crop_x = (input_w - game_crop_w) // 2       # centered
    game_crop = CropParams(x=game_crop_x, y=0, w=game_crop_w, h=input_h)

    # ------------------------------------------------------------------
    # Face (bottom) section — tight crop around detected face
    # The crop covers face_src_ratio of source height, AR-matched to bot section
    # ------------------------------------------------------------------
    face_crop_h_src = int(input_h * face_src_ratio) // 2 * 2   # source pixels tall
    face_crop_w_src = int(face_crop_h_src * output_w / bot_h) // 2 * 2

    # Clamp crop to source dimensions
    face_crop_h_src = min(face_crop_h_src, input_h)
    face_crop_w_src = min(face_crop_w_src, input_w)

    # Detect face centre (cx_rel, cy_rel) → fallback to centre
    cx_rel, cy_rel = 0.5, 0.5
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
        if centre:
            cx_rel, cy_rel = centre
            logger.info(f"[reframe/split] Face centre at ({cx_rel:.2f}, {cy_rel:.2f})")
        else:
            logger.info("[reframe/split] No face detected — centering face crop")
    except Exception as exc:
        logger.warning(f"[reframe/split] Face detection failed ({exc}) — centering")

    ideal_x = int(cx_rel * input_w - face_crop_w_src / 2)
    ideal_y = int(cy_rel * input_h - face_crop_h_src / 2)
    face_crop_x = max(0, min(ideal_x, input_w - face_crop_w_src))
    face_crop_y = max(0, min(ideal_y, input_h - face_crop_h_src))
    face_crop = CropParams(x=face_crop_x, y=face_crop_y, w=face_crop_w_src, h=face_crop_h_src)

    logger.info(
        f"[reframe/split] game_crop={game_crop} -> scale={output_w}x{top_h} | "
        f"face_crop={face_crop} -> scale={output_w}x{bot_h}"
    )

    return SplitLayout(
        game_crop=game_crop,
        face_crop=face_crop,
        top_h=top_h,
        bot_h=bot_h,
        output_w=output_w,
    )
