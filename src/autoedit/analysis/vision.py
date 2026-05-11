"""Vision analysis — face/subject detection for smart reframe.

Detects faces in video frames using OpenCV's built-in Haar cascade classifier
(no extra model download needed) and provides smoothed coordinates for
computing an optimal crop rectangle (e.g. 16:9 → 9:16 for TikTok/Shorts).

Future: swap the detector for MediaPipe Tasks FaceDetector once the model
download is bundled, or for YOLOv8-face for higher accuracy.

Typical usage
-------------
    from autoedit.analysis.vision import sample_face_positions, smooth_positions

    positions = sample_face_positions(video_path, start_sec, end_sec)
    smoothed  = smooth_positions(positions)
    cx, cy    = aggregate_position(smoothed)   # single representative point
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from loguru import logger


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FacePosition:
    """Detected face centre, normalised to [0, 1] relative to frame dimensions."""

    time_sec: float
    cx: float       # horizontal centre (0 = left, 1 = right)
    cy: float       # vertical centre   (0 = top,  1 = bottom)
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# 1-D Kalman smoother
# ---------------------------------------------------------------------------


@dataclass
class Kalman1D:
    """Minimal 1-D constant-velocity Kalman filter.

    State: [position, velocity].
    Suitable for smoothing a slowly-varying 1-D signal (e.g. face centre x).

    Parameters
    ----------
    process_noise    : how much the position is expected to drift per step
    measurement_noise: how noisy the observed measurements are
    """

    process_noise: float = 1e-3
    measurement_noise: float = 1e-2

    # Filter state (initialised on first observation)
    _x: float = field(default=0.0, init=False, repr=False)
    _v: float = field(default=0.0, init=False, repr=False)
    _p: float = field(default=1.0, init=False, repr=False)   # error covariance
    _initialised: bool = field(default=False, init=False, repr=False)

    def update(self, measurement: float) -> float:
        """Feed one observation, return the smoothed estimate."""
        if not self._initialised:
            self._x = measurement
            self._initialised = True
            return measurement

        # Predict
        x_pred = self._x + self._v
        p_pred = self._p + self.process_noise

        # Update (Kalman gain)
        k = p_pred / (p_pred + self.measurement_noise)
        self._x = x_pred + k * (measurement - x_pred)
        self._v = self._v + 0.1 * (measurement - x_pred)   # soft velocity update
        self._p = (1 - k) * p_pred

        return self._x


# ---------------------------------------------------------------------------
# Face detection (OpenCV Haar cascade)
# ---------------------------------------------------------------------------


def _get_face_cascade():  # type: ignore[return]
    """Return the OpenCV Haar face cascade, loading it lazily."""
    try:
        import cv2  # type: ignore[import-untyped]
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            raise RuntimeError(f"CascadeClassifier failed to load: {path}")
        return cascade
    except Exception as exc:
        logger.warning(f"[vision] Cannot load Haar cascade: {exc}")
        return None


def sample_face_positions(
    video_path: str,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    sample_interval_sec: float = 2.0,
    scale_factor: float = 1.1,
    min_neighbors: int = 5,
    min_face_size: int = 20,
) -> list[FacePosition]:
    """Sample *video_path* between *start_sec* and *end_sec* and return a list
    of detected face positions.

    Uses OpenCV's frontal-face Haar cascade — no extra model download needed.

    Parameters
    ----------
    video_path           : absolute path to the source video file
    start_sec / end_sec  : time range to sample (end_sec=None → end of video)
    sample_interval_sec  : seconds between sampled frames (default 2 s)
    scale_factor         : Haar detectMultiScale scale factor (1.05–1.3)
    min_neighbors        : Haar detectMultiScale min neighbours (higher = fewer FPs)
    min_face_size        : minimum face bounding box side in pixels

    Returns
    -------
    List of :class:`FacePosition` (may be empty if no faces detected).
    """
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("[vision] opencv-python not available — skipping face detection")
        return []

    cascade = _get_face_cascade()
    if cascade is None:
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"[vision] Cannot open video: {video_path}")
        return []

    fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_sec = total_frames / fps

    if end_sec is None or end_sec > total_sec:
        end_sec = total_sec

    positions: list[FacePosition] = []
    frames_sampled = 0

    current_sec = start_sec
    while current_sec < end_sec:
        frame_idx = int(current_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        frames_sampled += 1
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)   # improve contrast for low-light streams

        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=(min_face_size, min_face_size),
        )

        if len(faces) > 0:
            # Pick the largest detected face (most likely the webcam face)
            areas = [fw * fh for (fx, fy, fw, fh) in faces]
            best_idx = int(max(range(len(areas)), key=lambda i: areas[i]))
            fx, fy, fw, fh = faces[best_idx]

            cx = (fx + fw / 2) / w
            cy = (fy + fh / 2) / h
            cx = max(0.0, min(1.0, cx))
            cy = max(0.0, min(1.0, cy))
            # Confidence proxy: larger face → higher confidence
            conf = min(1.0, (fw * fh) / (w * h) * 20)
            positions.append(FacePosition(time_sec=current_sec, cx=cx, cy=cy, confidence=conf))
            logger.debug(
                f"[vision] t={current_sec:.1f}s  face @ ({cx:.2f}, {cy:.2f})  "
                f"size={fw}×{fh}  conf={conf:.2f}"
            )

        current_sec += sample_interval_sec

    cap.release()
    logger.info(
        f"[vision] Face detection: {len(positions)} detections "
        f"in {frames_sampled} sampled frames"
    )
    return positions


# ---------------------------------------------------------------------------
# Smoothing + aggregation
# ---------------------------------------------------------------------------


def smooth_positions(
    positions: Sequence[FacePosition],
    process_noise: float = 1e-3,
    measurement_noise: float = 1e-2,
) -> list[FacePosition]:
    """Apply independent 1-D Kalman filters to the x and y trajectories.

    Returns a new list with the same timestamps but smoothed cx/cy values.
    """
    if not positions:
        return []

    kx = Kalman1D(process_noise=process_noise, measurement_noise=measurement_noise)
    ky = Kalman1D(process_noise=process_noise, measurement_noise=measurement_noise)

    return [
        FacePosition(
            time_sec=p.time_sec,
            cx=kx.update(p.cx),
            cy=ky.update(p.cy),
            confidence=p.confidence,
        )
        for p in positions
    ]


def aggregate_position(
    positions: Sequence[FacePosition],
    weight_by_confidence: bool = True,
) -> tuple[float, float] | None:
    """Return a single (cx, cy) representative of the whole sequence.

    Uses confidence-weighted mean.  Returns ``None`` if *positions* is empty.
    """
    if not positions:
        return None

    if weight_by_confidence:
        total_w = sum(p.confidence for p in positions)
        cx = sum(p.cx * p.confidence for p in positions) / total_w
        cy = sum(p.cy * p.confidence for p in positions) / total_w
    else:
        cx = sum(p.cx for p in positions) / len(positions)
        cy = sum(p.cy for p in positions) / len(positions)

    return cx, cy
