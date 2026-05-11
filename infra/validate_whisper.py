#!/usr/bin/env python3
"""Validate remote transcription connection via OpenRouter."""
from __future__ import annotations

import base64
import struct
import tempfile
import wave
from pathlib import Path

import httpx

from autoedit.settings import settings


def _make_dummy_wav(path: Path, duration_sec: float = 2.0) -> Path:
    """Create a silent mono 16 kHz WAV file."""
    sr = 16_000
    n = int(duration_sec * sr)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return path


def main() -> int:
    print("=" * 60)
    print("Validating remote transcription (OpenRouter)")
    print("=" * 60)
    print(f"Base URL : {settings.TRANSCRIPTION_REMOTE_BASE_URL}")
    print(f"Model    : {settings.TRANSCRIPTION_REMOTE_MODEL}")
    key_tail = settings.TRANSCRIPTION_REMOTE_API_KEY[-6:] if settings.TRANSCRIPTION_REMOTE_API_KEY else ""
    print(f"API key  : ****{key_tail}")
    print()

    api_key = settings.TRANSCRIPTION_REMOTE_API_KEY or settings.OPENROUTER_API_KEY
    base_url = settings.TRANSCRIPTION_REMOTE_BASE_URL.rstrip("/")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/josemiguel/autoedit-ai",
        "X-Title": "AutoEdit AI",
        "Content-Type": "application/json",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = Path(tmpdir) / "test.wav"
        _make_dummy_wav(audio_path, duration_sec=2.0)
        print(f"Dummy audio: {audio_path} ({audio_path.stat().st_size} bytes)")

        audio_b64 = base64.b64encode(audio_path.read_bytes()).decode()

        # Attempt 1: Chat completions with audio in messages (OpenAI GPT-4o audio style)
        print("\n--- Attempt 1: Chat completions with audio content ---")
        chat_url = f"{base_url}/chat/completions"
        payload = {
            "model": settings.TRANSCRIPTION_REMOTE_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": "wav",
                            },
                        },
                    ],
                },
            ],
        }
        try:
            r = httpx.post(chat_url, headers=headers, json=payload, timeout=60.0)
            print(f"Status: {r.status_code}")
            print(f"Body: {r.text[:500]}")
        except Exception as exc:
            print(f"Error: {exc}")

        # Attempt 2: Direct audio endpoint with base64 JSON
        print("\n--- Attempt 2: POST /audio with base64 JSON ---")
        audio_url = f"{base_url}/audio"
        payload2 = {
            "model": settings.TRANSCRIPTION_REMOTE_MODEL,
            "audio": audio_b64,
            "format": "wav",
        }
        try:
            r2 = httpx.post(audio_url, headers=headers, json=payload2, timeout=60.0)
            print(f"Status: {r2.status_code}")
            print(f"Body: {r2.text[:500]}")
        except Exception as exc:
            print(f"Error: {exc}")

        # Attempt 3: Completions endpoint with prompt containing audio
        print("\n--- Attempt 3: Completions with audio prompt ---")
        completions_url = f"{base_url}/completions"
        payload3 = {
            "model": settings.TRANSCRIPTION_REMOTE_MODEL,
            "prompt": f"Transcribe this audio: data:audio/wav;base64,{audio_b64}",
            "max_tokens": 500,
        }
        try:
            r3 = httpx.post(completions_url, headers=headers, json=payload3, timeout=60.0)
            print(f"Status: {r3.status_code}")
            print(f"Body: {r3.text[:500]}")
        except Exception as exc:
            print(f"Error: {exc}")

    print("\n" + "=" * 60)
    print("Validation complete")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
