"""Remote transcription engine using an OpenAI-compatible API."""

from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from autoedit.settings import settings


def _get_api_key() -> str:
    """Return the API key to use for remote transcription."""
    key = settings.TRANSCRIPTION_REMOTE_API_KEY
    if not key:
        key = settings.OPENROUTER_API_KEY
    if not key:
        raise RuntimeError(
            "Remote transcription requires TRANSCRIPTION_REMOTE_API_KEY or OPENROUTER_API_KEY"
        )
    return key


def transcribe_remote(
    audio_path: str,
    language: str = "es",
    model: str | None = None,
) -> dict[str, Any]:
    """Transcribe audio via a remote OpenAI-compatible API.

    Defaults to OpenAI's whisper-1 endpoint, but can be pointed to Groq,
    OpenRouter, or any other compatible provider via settings.
    """
    model = model or settings.TRANSCRIPTION_REMOTE_MODEL
    base_url = settings.TRANSCRIPTION_REMOTE_BASE_URL.rstrip("/")
    api_key = _get_api_key()
    url = f"{base_url}/audio/transcriptions"

    logger.info(f"[transcribe:remote] POST {url} model={model} lang={language}")

    with open(audio_path, "rb") as audio_file:
        files = {"file": (Path(audio_path).name, audio_file, "audio/mpeg")}
        data = {
            "model": model,
            "language": language if language != "auto" else None,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        headers = {"Authorization": f"Bearer {api_key}"}

        response = httpx.post(
            url,
            headers=headers,
            data=data,
            files=files,
            timeout=300.0,
        )

    response.raise_for_status()
    payload = response.json()

    # Normalize remote response to the same schema used by the local engine
    segments = []
    raw_segments = payload.get("segments", [])
    for seg in raw_segments:
        seg_dict: dict[str, Any] = {
            "id": seg.get("id", 0),
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "text": seg.get("text", "").strip(),
            "words": [
                {
                    "word": w.get("word", "").strip(),
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                    "probability": w.get("probability", 1.0),
                }
                for w in seg.get("words", [])
            ],
        }
        segments.append(seg_dict)

    return {
        "language": payload.get("language", language),
        "language_probability": 1.0,
        "duration": payload.get("duration", 0.0),
        "segments": segments,
    }
