"""Transcription dispatcher — local faster-whisper or remote API."""

from pathlib import Path
from typing import Any

from loguru import logger

from autoedit.analysis.transcribe_local import transcribe_local
from autoedit.analysis.transcribe_remote import transcribe_remote
from autoedit.settings import settings


def transcribe_audio(
    audio_path: str,
    output_path: str,
    language: str = "es",
) -> dict[str, Any]:
    """Transcribe audio using the configured provider.

    Args:
        audio_path: Path to the audio file.
        output_path: Where to write the JSON transcript.
        language: Language code (es/en/auto).

    Returns:
        Normalized dict with language, duration, and segments (with words).
    """
    provider = settings.TRANSCRIPTION_PROVIDER.lower()
    logger.info(f"[transcribe] provider={provider} audio={audio_path}")

    if provider == "remote":
        result = transcribe_remote(
            audio_path=audio_path,
            language=language,
        )
    else:
        result = transcribe_local(
            audio_path=audio_path,
            language=language,
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        import json

        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(
        f"[transcribe] complete: {len(result.get('segments', []))} segments, "
        f"lang={result.get('language')}"
    )
    return result
