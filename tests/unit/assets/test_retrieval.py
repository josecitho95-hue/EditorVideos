"""Tests for asset retrieval, embeddings, and deduplication."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from autoedit.assets.deduplication import filter_recent_usage
from autoedit.assets.embeddings import CLIP_DIM, embed_asset, embed_text
from autoedit.assets.retrieval import AssetRetrieval
from autoedit.domain.asset import Asset, AssetKind
from autoedit.domain.highlight import Intent
from autoedit.domain.ids import AssetId

# ---------------------------------------------------------------------------
# Shared CLIP mock — avoids loading the real model (~340 MB) in unit tests.
# Returned vectors are random but L2-normalised to match production behaviour.
# ---------------------------------------------------------------------------

_RNG = np.random.default_rng(42)


def _fake_clip_vector(n: int = 1) -> list[list[float]]:
    """Return n random L2-normalised 512-dim vectors."""
    vecs = _RNG.standard_normal((n, CLIP_DIM)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs.tolist()


@pytest.fixture(autouse=True)
def mock_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch _get_clip so no real model is loaded during unit tests.

    Returns L2-normalised random 512-dim vectors with correct batch sizes.
    """
    import torch

    import autoedit.assets.embeddings as emb_module

    # --- Fake model ----------------------------------------------------------
    fake_model = MagicMock()
    # parameters() is called to detect the device
    fake_param = MagicMock()
    fake_param.device = torch.device("cpu")
    fake_model.parameters.return_value = iter([fake_param])

    def _fake_encode(tokens: torch.Tensor, **_kw: object) -> torch.Tensor:
        """Return n random L2-normalised unit vectors matching the batch size."""
        n = tokens.shape[0] if isinstance(tokens, torch.Tensor) else 1
        vecs = torch.tensor(_fake_clip_vector(n), dtype=torch.float32)
        return vecs

    fake_model.encode_text.side_effect = _fake_encode
    fake_model.encode_image.side_effect = _fake_encode

    # --- Fake tokenizer — returns a real tensor so shape[0] is correct -------
    def _fake_tokenizer(texts: list[str] | str, **_kw: object) -> torch.Tensor:
        n = 1 if isinstance(texts, str) else len(texts)
        return torch.zeros(n, 77, dtype=torch.long)  # 77 = CLIP context length

    # --- Fake image preprocessor ---------------------------------------------
    def _fake_preprocess(img: object) -> torch.Tensor:
        return torch.zeros(3, 224, 224)

    monkeypatch.setattr(emb_module, "_model", fake_model)
    monkeypatch.setattr(emb_module, "_preprocess", _fake_preprocess)
    monkeypatch.setattr(emb_module, "_tokenizer", _fake_tokenizer)


# ---------------------------------------------------------------------------
# TC-AST-001 — text embedding generation
# ---------------------------------------------------------------------------


class TestEmbedText:
    """embed_text returns 512-dim CLIP vectors (with mocked model)."""

    def test_single_text_returns_one_vector(self) -> None:
        with patch("torch.no_grad"):
            result = embed_text("This is a test sentence")
        assert len(result) == 1
        assert len(result[0]) == CLIP_DIM, f"Expected {CLIP_DIM}-dim, got {len(result[0])}"

    def test_multiple_texts_returns_multiple_vectors(self) -> None:
        with patch("torch.no_grad"):
            result = embed_text(["First sentence", "Second sentence"])
        assert len(result) == 2
        assert all(len(v) == CLIP_DIM for v in result)

    def test_dim_constant_is_512(self) -> None:
        assert CLIP_DIM == 512, f"CLIP_DIM must be 512, got {CLIP_DIM}"


# ---------------------------------------------------------------------------
# TC-AST-002 — asset embedding from metadata
# ---------------------------------------------------------------------------


class TestEmbedAsset:
    """embed_asset combines metadata and returns a 512-dim vector."""

    def test_returns_clip_dim_vector(self) -> None:
        with patch("torch.no_grad"):
            result = embed_asset(
                description="A funny fail meme",
                tags=["meme", "fail", "funny"],
                intent_affinity=["fail", "funny_moment"],
            )
        assert len(result) == CLIP_DIM
        assert all(isinstance(v, float) for v in result)

    def test_empty_description_uses_tags(self) -> None:
        with patch("torch.no_grad"):
            result = embed_asset(description="", tags=["boom"], intent_affinity=["fail"])
        assert len(result) == CLIP_DIM


# ---------------------------------------------------------------------------
# TC-AST-003 — AssetRetrieval Qdrant integration
# ---------------------------------------------------------------------------


class TestAssetRetrieval:
    """AssetRetrieval delegates correctly to the repository."""

    @patch("autoedit.assets.retrieval.embed_text")
    @patch("autoedit.assets.retrieval.AssetRepository")
    def test_search_visual_returns_assets(
        self, mock_repo_cls: Any, mock_embed: Any
    ) -> None:
        mock_embed.return_value = [_fake_clip_vector(1)[0]]

        mock_asset = Asset(
            id=AssetId("asset-001"),
            kind=AssetKind.MEME,
            file_path="/tmp/meme.png",
            sha256="abc123",
            tags=["fail", "meme"],
            intent_affinity=["fail"],
        )
        mock_repo = MagicMock()
        mock_repo.search_qdrant.return_value = [
            {"id": "asset-001", "score": 0.95, "payload": {}}
        ]
        mock_repo.get.return_value = mock_asset
        mock_repo_cls.return_value = mock_repo

        results = AssetRetrieval().search_visual(Intent.FAIL, top_k=3)

        assert len(results) == 1
        assert results[0].id == "asset-001"
        mock_repo.search_qdrant.assert_called_once()
        # Confirm query vector has correct dimension
        call_kwargs = mock_repo.search_qdrant.call_args
        qv = call_kwargs.kwargs.get("query_vector") or call_kwargs.args[0]
        assert len(qv) == CLIP_DIM

    @patch("autoedit.assets.retrieval.embed_text")
    @patch("autoedit.assets.retrieval.AssetRepository")
    def test_search_audio_returns_assets(
        self, mock_repo_cls: Any, mock_embed: Any
    ) -> None:
        mock_embed.return_value = [_fake_clip_vector(1)[0]]

        mock_asset = Asset(
            id=AssetId("asset-002"),
            kind=AssetKind.AUDIO_SFX,
            file_path="/tmp/boom.wav",
            sha256="def456",
            tags=["sfx", "explosion"],
            intent_affinity=["fail"],
        )
        mock_repo = MagicMock()
        mock_repo.search_qdrant.return_value = [
            {"id": "asset-002", "score": 0.88, "payload": {}}
        ]
        mock_repo.get.return_value = mock_asset
        mock_repo_cls.return_value = mock_repo

        results = AssetRetrieval().search_audio(Intent.FAIL, top_k=3)

        assert len(results) == 1
        assert results[0].kind == AssetKind.AUDIO_SFX

    @patch("autoedit.assets.retrieval.embed_text")
    @patch("autoedit.assets.retrieval.AssetRepository")
    def test_search_empty_returns_empty(
        self, mock_repo_cls: Any, mock_embed: Any
    ) -> None:
        mock_embed.return_value = [_fake_clip_vector(1)[0]]
        mock_repo = MagicMock()
        mock_repo.search_qdrant.return_value = []
        mock_repo_cls.return_value = mock_repo

        results = AssetRetrieval().search_visual(Intent.OTHER, top_k=3)
        assert results == []

    @patch("autoedit.assets.retrieval.embed_image")
    @patch("autoedit.assets.retrieval.embed_text")
    @patch("autoedit.assets.retrieval.AssetRepository")
    def test_add_image_asset_uses_image_encoder(
        self,
        mock_repo_cls: Any,
        mock_embed_text: Any,
        mock_embed_image: Any,
        tmp_path: Path,
    ) -> None:
        """PNG assets must be encoded with the image encoder, not text."""
        png = tmp_path / "meme.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # fake PNG bytes

        mock_embed_image.return_value = _fake_clip_vector(1)[0]
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        AssetRetrieval().add_asset(
            file_path=png,
            kind=AssetKind.MEME,
            tags=["meme"],
            intent_affinity=["fail"],
            description="A meme",
        )

        mock_embed_image.assert_called_once()
        mock_embed_text.assert_not_called()

    @patch("autoedit.assets.retrieval.embed_image")
    @patch("autoedit.assets.retrieval.embed_text")
    @patch("autoedit.assets.retrieval.AssetRepository")
    def test_add_audio_asset_uses_text_encoder(
        self,
        mock_repo_cls: Any,
        mock_embed_text: Any,
        mock_embed_image: Any,
        tmp_path: Path,
    ) -> None:
        """WAV assets must be encoded with the text encoder (CLAP later)."""
        wav = tmp_path / "boom.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 40)  # minimal fake WAV

        mock_embed_text.return_value = [_fake_clip_vector(1)[0]]
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        AssetRetrieval().add_asset(
            file_path=wav,
            kind=AssetKind.AUDIO_SFX,
            tags=["explosion"],
            intent_affinity=["fail"],
            description="Big boom SFX",
        )

        mock_embed_text.assert_called_once()
        mock_embed_image.assert_not_called()


# ---------------------------------------------------------------------------
# TC-AST-004 — filter recently used assets
# ---------------------------------------------------------------------------


class TestAssetDeduplication:
    @patch("autoedit.assets.deduplication.get_session")
    def test_filters_recently_used(self, mock_get_session: Any) -> None:
        asset1 = Asset(
            id=AssetId("asset-001"),
            kind=AssetKind.MEME,
            file_path="/tmp/meme.png",
            sha256="abc",
            tags=[],
            intent_affinity=[],
        )
        asset2 = Asset(
            id=AssetId("asset-002"),
            kind=AssetKind.MEME,
            file_path="/tmp/meme2.png",
            sha256="def",
            tags=[],
            intent_affinity=[],
        )

        mock_usage = MagicMock()
        mock_usage.asset_id = "asset-001"
        mock_usage.timeline_start = 0.0

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = [mock_usage]
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = filter_recent_usage([asset1, asset2])

        assert len(result) == 1
        assert result[0].id == "asset-002"

    def test_empty_input_returns_empty(self) -> None:
        assert filter_recent_usage([]) == []
