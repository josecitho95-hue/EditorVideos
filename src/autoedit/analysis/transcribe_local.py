"""Local transcription engine using faster-whisper."""

from typing import Any

from autoedit.settings import settings
from autoedit.utils.cuda_dlls import register_nvidia_dlls

# Ensure NVIDIA DLLs are discoverable on Windows before loading native extensions
register_nvidia_dlls()

from faster_whisper import WhisperModel  # noqa: E402
from loguru import logger


def transcribe_local(
    audio_path: str,
    language: str = "es",
    model_size: str | None = None,
) -> dict[str, Any]:
    """Transcribe audio with faster-whisper locally.

    Returns the Whisper output dict with segments and word-level timestamps.
    """
    model_size = model_size or settings.TRANSCRIPTION_LOCAL_MODEL
    model_dir = str(settings.data_dir / "models" / f"faster-whisper-{model_size}")

    logger.info(f"[transcribe:local] Loading model {model_size} from {model_dir}")

    # Try CUDA first, fall back to CPU if unavailable or DLLs missing
    for device, compute_type in (
        ("cuda", "int8_float16"),
        ("cpu", "int8"),
    ):
        try:
            logger.info(f"[transcribe:local] Trying device={device}, compute_type={compute_type}")
            model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=model_dir,
            )
            logger.info(f"[transcribe:local] Using device={device}, compute_type={compute_type}")
            break
        except RuntimeError as exc:
            if "cuda" in str(exc).lower() or "cublas" in str(exc).lower():
                logger.warning(f"[transcribe:local] CUDA init failed ({exc}), retrying CPU")
                continue
            raise
    else:
        raise RuntimeError("Unable to load WhisperModel on cuda or cpu")

    segments_iter, info = model.transcribe(
        audio_path,
        language=language if language != "auto" else None,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
        word_timestamps=True,
    )

    segments = []
    for segment in segments_iter:
        seg_dict: dict[str, Any] = {
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
            "words": [
                {
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                    "probability": w.probability,
                }
                for w in (segment.words or [])
            ],
        }
        segments.append(seg_dict)

    return {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": segments,
    }
