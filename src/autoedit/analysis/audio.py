"""Audio analysis using librosa and pyloudnorm."""

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from loguru import logger

from autoedit.domain.signals import AudioSignal


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

        signals.append(
            AudioSignal(
                t_sec=float(t),
                rms_db=float(rms_db),
                loudness_lufs=float(loudness),
                pitch_hz=float(pitch_hz) if pitch_hz else None,
            )
        )

    logger.info(f"Audio analysis complete: {len(signals)} seconds")
    return signals
