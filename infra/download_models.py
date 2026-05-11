#!/usr/bin/env python3
"""Download ML models required by AutoEdit AI.

Usage:
    uv run python infra/download_models.py
"""
from __future__ import annotations

import sys

from autoedit.settings import settings


def download_faster_whisper() -> None:
    """Download faster-whisper large-v3 model."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        print(f"ERROR: faster-whisper not installed: {exc}")
        sys.exit(1)

    model_dir = settings.data_dir / "models" / "faster-whisper-large-v3"
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading faster-whisper large-v3 to {model_dir} ...")
    # Instantiating the model triggers the download
    _ = WhisperModel(
        "large-v3",
        device="cpu",          # CPU is sufficient for download
        compute_type="int8",
        download_root=str(model_dir),
    )
    print("faster-whisper large-v3 ready.")


def ensure_model_dirs() -> None:
    """Create placeholder directories for models managed in future sprints."""
    # CLIP ViT-B/32 — Sprint 4+ (requires transformers or open-clip)
    clip_dir = settings.data_dir / "models" / "clip-vit-b-32"
    clip_dir.mkdir(parents=True, exist_ok=True)
    (clip_dir / "README.txt").write_text(
        "CLIP ViT-B/32 model placeholder.\n"
        "Will be downloaded automatically when assets/retrieval.py is wired.\n"
        "Requires: transformers, torch\n"
    )
    print(f"Placeholder created: {clip_dir}")

    # F5-TTS — Sprint 5+ (requires f5-tts package)
    f5_dir = settings.data_dir / "models" / "f5-tts"
    f5_dir.mkdir(parents=True, exist_ok=True)
    (f5_dir / "README.txt").write_text(
        "F5-TTS model placeholder.\n"
        "Will be downloaded automatically when tts/ module is wired.\n"
        "Requires: f5-tts, torch\n"
    )
    print(f"Placeholder created: {f5_dir}")


def main() -> int:
    print("=" * 60)
    print("AutoEdit AI — Model Download")
    print("=" * 60)

    download_faster_whisper()
    ensure_model_dirs()

    print("=" * 60)
    print("All model directories ready.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
