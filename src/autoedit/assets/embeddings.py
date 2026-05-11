"""Asset embedding service using OpenCLIP (ViT-B/32).

All vectors are 512-dimensional and L2-normalised so that cosine similarity
equals dot-product.  Both visual and audio Qdrant collections use the same
dimension; visual assets are encoded with the CLIP *image* encoder while audio
assets (SFX, music) are encoded with the CLIP *text* encoder applied to their
description + tags.  This keeps the system to a single model (~350 MB VRAM)
and lets text-based intent queries retrieve both kinds of assets.

CLAP (audio-waveform → embedding) can be layered on top later when waveform
similarity search is needed (Sprint 6+).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
from loguru import logger

if TYPE_CHECKING:
    import open_clip  # noqa: F401 — type hints only

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLIP_MODEL: str = "ViT-B-32"
CLIP_PRETRAINED: str = "openai"       # ~340 MB; cached in ~/.cache/huggingface
CLIP_DIM: int = 512                   # all Qdrant collections must use this size

# ---------------------------------------------------------------------------
# Lazy singletons (loaded once, held for process lifetime)
# ---------------------------------------------------------------------------

_model: "open_clip.CLIP | None" = None
_preprocess = None          # torchvision Transform for images
_tokenizer = None           # CLIP tokenizer for text


def _get_clip() -> tuple:
    """Load (and cache) the CLIP model, preprocessor, and tokenizer."""
    global _model, _preprocess, _tokenizer
    if _model is None:
        import open_clip as _oc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(
            f"Loading CLIP model {CLIP_MODEL!r} pretrained={CLIP_PRETRAINED!r} on {device}"
        )
        model, _, preprocess = _oc.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED
        )
        model = model.to(device).eval()
        tokenizer = _oc.get_tokenizer(CLIP_MODEL)

        _model = model
        _preprocess = preprocess
        _tokenizer = tokenizer
        logger.info("CLIP model ready")

    return _model, _preprocess, _tokenizer


def _device() -> torch.device:
    model, _, _ = _get_clip()
    return next(model.parameters()).device  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_text(texts: str | list[str]) -> list[list[float]]:
    """Embed one or more text strings with the CLIP text encoder.

    Returns:
        List of L2-normalised 512-dim vectors.
    """
    if isinstance(texts, str):
        texts = [texts]

    model, _, tokenizer = _get_clip()
    dev = _device()

    with torch.no_grad():
        tokens = tokenizer(texts).to(dev)           # type: ignore[operator]
        features = model.encode_text(tokens)        # type: ignore[union-attr]
        features = features / features.norm(dim=-1, keepdim=True)

    return features.cpu().numpy().tolist()


def embed_image(path: Path | str) -> list[float]:
    """Embed an image file with the CLIP image encoder.

    Returns:
        L2-normalised 512-dim vector.
    """
    from PIL import Image

    model, preprocess, _ = _get_clip()
    dev = _device()

    img = Image.open(path).convert("RGB")
    tensor = preprocess(img).unsqueeze(0).to(dev)   # type: ignore[operator]

    with torch.no_grad():
        features = model.encode_image(tensor)       # type: ignore[union-attr]
        features = features / features.norm(dim=-1, keepdim=True)

    return features.cpu().numpy()[0].tolist()


def embed_asset(description: str, tags: list[str], intent_affinity: list[str]) -> list[float]:
    """Create a 512-dim text embedding for an asset from its metadata.

    Concatenates description, tags, and intent affinity into a single search
    string and runs it through the CLIP text encoder.

    Use :func:`embed_image` instead when you want a content-based (image)
    embedding for visual assets.
    """
    parts = [description] if description else []
    parts.extend(tags)
    parts.extend(intent_affinity)
    return embed_text(" ".join(parts))[0]
