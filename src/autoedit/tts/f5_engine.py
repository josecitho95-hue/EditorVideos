"""F5-TTS synthesis engine — voice cloning with local GPU inference.

Architecture
------------
- Lazy model loading: the 800 MB F5-TTS checkpoint is downloaded from
  HuggingFace on first synthesis call and cached locally.
- Protocol: exposes ``synthesize(text, voice_id, output_path) -> float``
  compatible with :class:`~autoedit.tts.narration_cache.NarrationCache`.
- VRAM budget: ~3-4 GB (RTX 4070 Mobile can comfortably run this after
  Whisper and CLIP have released their memory).

Voice profiles
--------------
Each ``voice_id`` maps to a :class:`~autoedit.storage.db.VoiceProfileModel`
row in SQLite.  Use ``autoedit voice register`` to add a profile before
running E8.  If the profile is missing, synthesis raises ``ValueError``.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Windows workaround: torchaudio.load tries the torchcodec backend first,
# which requires FFmpeg "full-shared" DLLs not shipped in standard installs.
# We replace it with a soundfile-based implementation that works everywhere.
# ---------------------------------------------------------------------------

_TORCHAUDIO_PATCHED = False


def _patch_torchaudio_load() -> None:
    """Monkey-patch torchaudio.load to use soundfile instead of torchcodec.

    The patch is idempotent — calling it multiple times is safe.
    The replacement returns an identical (tensor, sample_rate) tuple so
    nothing downstream in F5-TTS needs to change.
    """
    global _TORCHAUDIO_PATCHED
    if _TORCHAUDIO_PATCHED:
        return

    try:
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        _original_load = torchaudio.load  # keep reference for debugging

        def _sf_load(
            filepath: str | Path,
            *args: Any,
            **kwargs: Any,
        ) -> tuple[Any, int]:
            """soundfile-based replacement for torchaudio.load."""
            data, sr = sf.read(str(filepath), always_2d=True, dtype="float32")
            # soundfile: (samples, channels) → torchaudio: (channels, samples)
            tensor = torch.from_numpy(data.T)
            return tensor, sr

        torchaudio.load = _sf_load
        # Also patch the internal reference used by f5_tts.model.utils_infer
        try:
            import f5_tts.model.utils_infer as _ui
            _ui.torchaudio.load = _sf_load  # type: ignore[attr-defined]
        except Exception:
            pass

        _TORCHAUDIO_PATCHED = True
        logger.debug("[F5-TTS] torchaudio.load patched to use soundfile (Windows workaround)")

    except Exception as exc:
        logger.warning(f"[F5-TTS] Could not patch torchaudio.load: {exc}")


def _wav_duration(path: Path) -> float:
    """Read duration from a WAV header. Returns 0.0 on error."""
    try:
        with wave.open(str(path)) as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


class F5TTSEngine:
    """Voice-cloning TTS engine backed by F5-TTS (SWivid/F5-TTS).

    Usage::

        engine = F5TTSEngine()
        duration = engine.synthesize(
            text="Increible jugada, lo hizo perfecto!",
            voice_id="me_v1",
            output_path="out.wav",
        )
    """

    # F5-TTS model variant — "F5TTS_v1_Base" is the recommended checkpoint.
    MODEL_NAME: str = "F5TTS_v1_Base"

    def __init__(self, device: str | None = None) -> None:
        """
        Args:
            device: Force a specific device string ("cuda", "cpu", …).
                    When *None* (default), uses CUDA if available, else CPU.
        """
        import torch

        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._f5: Any = None          # lazy-loaded F5TTS instance
        self._loaded_device: str = "" # track which device was used

    # ------------------------------------------------------------------
    # Public protocol — compatible with NarrationCache
    # ------------------------------------------------------------------

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        """Synthesise *text* in *voice_id*'s cloned voice and write WAV.

        Args:
            text:        Spanish narration text to synthesise (≤ 400 chars
                         recommended per call for best prosody).
            voice_id:    ID of a registered voice profile (e.g. ``"me_v1"``).
            output_path: Destination path for the output WAV file (24 kHz mono).

        Returns:
            Duration in seconds of the generated audio.

        Raises:
            ValueError: If *voice_id* is not registered in the DB.
            RuntimeError: If F5-TTS synthesis fails.
        """
        from autoedit.storage.repositories.voices import VoiceProfileRepository

        profile = VoiceProfileRepository().get(voice_id)
        if profile is None:
            raise ValueError(
                f"Voice profile '{voice_id}' not found. "
                "Run: autoedit voice register <audio> <voice_id>"
            )

        model = self._get_model()
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(
            f"[F5-TTS] Synthesising {len(text)} chars as '{voice_id}' "
            f"ref={Path(profile.ref_audio_path).name}"
        )

        try:
            model.infer(
                ref_file=profile.ref_audio_path,
                ref_text=profile.ref_text,
                gen_text=text,
                file_wave=str(out_path),
                seed=-1,            # random seed for natural variation
                remove_silence=True,
            )
        except Exception as exc:
            raise RuntimeError(f"F5-TTS synthesis failed: {exc}") from exc

        duration = _wav_duration(out_path)
        logger.info(f"[F5-TTS] Generated {duration:.2f}s -> {out_path.name}")
        return duration

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> Any:
        """Return (cached) F5TTS model instance, loading if necessary."""
        if self._f5 is not None and self._loaded_device == self._device:
            return self._f5

        # Apply soundfile patch before any torchaudio calls
        _patch_torchaudio_load()

        logger.info(f"[F5-TTS] Loading model '{self.MODEL_NAME}' on {self._device} ...")
        try:
            from f5_tts.api import F5TTS

            self._f5 = F5TTS(model=self.MODEL_NAME, device=self._device)
            self._loaded_device = self._device
            logger.info("[F5-TTS] Model ready")
        except Exception as exc:
            raise RuntimeError(f"Failed to load F5-TTS model: {exc}") from exc

        return self._f5
