"""Audio analysis using librosa and pyloudnorm.

Laughter / reaction detection
------------------------------
A lightweight acoustic heuristic is applied per second using three features:

* **Zero Crossing Rate (ZCR)** — laughter oscillates rapidly; ZCR > 0.08 is a
  strong indicator.
* **Spectral centroid** — laughter energy is concentrated in the 1-4 kHz range,
  higher than typical speech.
* **Amplitude modulation** — the "ha-ha-ha" pattern creates rhythmic RMS peaks;
  we measure std/mean of sub-frame RMS.

The three scores are linearly combined into a ``laughter_prob`` in [0, 1].
These thresholds are tuned for Twitch gaming streams with a microphone at ~50 cm
distance, sampled at 16 kHz mono.
"""

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from loguru import logger

from autoedit.domain.signals import AudioSignal


# ---------------------------------------------------------------------------
# Laughter detection helper
# ---------------------------------------------------------------------------

def _laughter_prob(chunk: np.ndarray, sr: int) -> float:
    """Return an estimated laughter probability [0, 1] for a 1-second chunk.

    Uses ZCR, spectral centroid, and amplitude modulation as acoustic proxies.
    Thresholds calibrated for 16 kHz mono speech/gaming audio.
    """
    if len(chunk) < sr // 4:      # need at least 250 ms
        return 0.0
    try:
        # 1. ZCR — rapid oscillation typical of laughter
        zcr = float(librosa.feature.zero_crossing_rate(chunk).mean())
        # Speech: ~0.04-0.08; Laughter: 0.08-0.22+
        zcr_score = float(np.clip((zcr - 0.04) / (0.22 - 0.04), 0.0, 1.0))

        # 2. Spectral centroid — laughter skews toward higher frequencies
        centroid = float(librosa.feature.spectral_centroid(y=chunk, sr=sr).mean())
        # Map [1000 Hz, 4000 Hz] → [0, 1]
        centroid_score = float(np.clip((centroid - 1_000) / 3_000, 0.0, 1.0))

        # 3. Amplitude modulation — ha-ha-ha rhythmic loudness bursts
        frame_len = max(sr // 20, 32)   # 50 ms sub-frames
        hop_len = frame_len // 2
        if len(chunk) >= frame_len:
            frames = librosa.util.frame(chunk, frame_length=frame_len, hop_length=hop_len)
            rms_frames = np.sqrt((frames.astype(float) ** 2).mean(axis=0))
            mean_rms = float(rms_frames.mean())
            if mean_rms > 1e-6:         # skip silence
                var_score = float(np.clip(rms_frames.std() / mean_rms / 0.8, 0.0, 1.0))
            else:
                var_score = 0.0
        else:
            var_score = 0.0

        # Weighted combination — all three must be elevated for high confidence
        prob = 0.40 * zcr_score + 0.30 * centroid_score + 0.30 * var_score
        return float(np.clip(prob, 0.0, 1.0))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_audio(audio_path: str, sr: int = 16000) -> list[AudioSignal]:
    """Extract audio signals (RMS, loudness, pitch) per second.

    Returns a list of AudioSignal, one per second.
    """
    logger.info(f"Analyzing audio: {audio_path}")
    y, file_sr = sf.read(audio_path)

    # Convert to mono if stereo
    if y.ndim > 1:
        y = y.mean(axis=1)

    # Resample to target sr if needed
    if file_sr != sr:
        y = librosa.resample(y, orig_sr=file_sr, target_sr=sr)
        file_sr = sr

    meter = pyln.Meter(file_sr)
    duration_sec = len(y) / file_sr
    n_seconds = int(duration_sec)

    signals: list[AudioSignal] = []

    for t in range(n_seconds):
        start = t * sr
        end = start + sr
        chunk = y[start:end]

        # RMS in dB
        rms = np.sqrt(np.mean(chunk**2))
        rms_db = 20 * np.log10(rms + 1e-10)

        # Loudness (ITU-R BS.1770)
        try:
            loudness = meter.integrated_loudness(chunk)
        except Exception:
            loudness = -70.0

        # Pitch (fundamental frequency via piptrack)
        try:
            pitches, magnitudes = librosa.piptrack(y=chunk, sr=sr)
            pitch_vals = pitches[magnitudes > np.median(magnitudes)]
            pitch_hz = float(np.median(pitch_vals)) if len(pitch_vals) > 0 else None
        except Exception:
            pitch_hz = None

        # Laughter / reaction probability
        laugh_prob = _laughter_prob(chunk, sr)

        signals.append(
            AudioSignal(
                t_sec=float(t),
                rms_db=float(rms_db),
                loudness_lufs=float(loudness),
                pitch_hz=float(pitch_hz) if pitch_hz else None,
                laughter_prob=laugh_prob,
            )
        )

    peak_laugh = max((s.laughter_prob for s in signals), default=0.0)
    logger.info(
        f"[audio] Analysis complete: {len(signals)}s | "
        f"peak laughter_prob={peak_laugh:.2f}"
    )
    return signals
