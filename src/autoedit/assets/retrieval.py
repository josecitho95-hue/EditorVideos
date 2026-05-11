"""Asset retrieval using Qdrant semantic search.

Collection layout
-----------------
``assets_visual``  — 512-dim CLIP vectors (image encoder for visual assets,
                     text encoder for text queries).
``assets_audio``   — 512-dim CLIP vectors (text encoder for both assets and
                     queries; CLAP audio encoder reserved for Sprint 6+).

Both collections use :data:`~autoedit.assets.embeddings.CLIP_DIM` = 512.
"""

from pathlib import Path
from typing import Any

from loguru import logger

from autoedit.assets.embeddings import CLIP_DIM, embed_image, embed_text
from autoedit.domain.asset import Asset, AssetKind
from autoedit.domain.highlight import Intent
from autoedit.storage.repositories.assets import AssetRepository

# Qdrant collection names (must be created before first use — see ensure_collections)
_VISUAL_COLLECTION = "assets_visual"
_AUDIO_COLLECTION = "assets_audio"


def ensure_collections(qdrant_url: str | None = None) -> None:
    """Create Qdrant collections if they do not already exist.

    If a collection exists but was created with the wrong vector dimension
    (e.g. left over from a previous embedding model), it is automatically
    deleted and recreated with the current :data:`CLIP_DIM`.

    Call this once at application startup (e.g. from the CLI or worker init)
    before indexing or querying assets.

    Args:
        qdrant_url: Override the URL from settings (useful in tests).
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    from autoedit.settings import settings

    url = qdrant_url or settings.QDRANT_URL
    client = QdrantClient(url=url)

    existing_names = {c.name for c in client.get_collections().collections}

    for name in (_VISUAL_COLLECTION, _AUDIO_COLLECTION):
        if name in existing_names:
            # Check that the stored dimension matches the current model
            info = client.get_collection(name)
            stored_dim = info.config.params.vectors.size  # type: ignore[union-attr]
            if stored_dim == CLIP_DIM:
                logger.debug(f"[Qdrant] Collection {name!r} already exists (dim={CLIP_DIM}) — skipping")
                continue
            # Wrong dimension — drop and recreate
            logger.warning(
                f"[Qdrant] Collection {name!r} has dim={stored_dim}, expected {CLIP_DIM} — recreating"
            )
            client.delete_collection(name)

        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=CLIP_DIM, distance=Distance.COSINE),
        )
        logger.info(f"[Qdrant] Created collection {name!r} (dim={CLIP_DIM}, cosine)")


_INTENT_DESCRIPTIONS: dict[Intent, str] = {
    Intent.FAIL: "fail mistake falling funny meme reaction",
    Intent.WIN: "victory win achievement success celebration",
    Intent.REACTION: "reaction surprise shock scared amazed",
    Intent.RAGE: "rage angry tilt frustration mad screaming",
    Intent.FUNNY_MOMENT: "funny hilarious joke comedy humor",
    Intent.SKILL_PLAY: "skill clutch epic play amazing pro",
    Intent.WHOLESOME: "wholesome heartwarming cute kind sweet",
    Intent.OTHER: "miscellaneous",
}

_VISUAL_KINDS: frozenset[AssetKind] = frozenset(
    {AssetKind.VISUAL_IMAGE, AssetKind.VISUAL_VIDEO, AssetKind.MEME}
)
_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
)


class AssetRetrieval:
    """Search for visual/audio assets matching a highlight intent."""

    def __init__(self, repository: AssetRepository | None = None) -> None:
        self._repo = repository or AssetRepository()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def _embed_query(self, intent: Intent) -> list[float]:
        """CLIP text embedding for an intent label (used at query time)."""
        text = _INTENT_DESCRIPTIONS.get(intent, intent.value)
        return embed_text(text)[0]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_visual(self, intent: Intent, top_k: int = 3) -> list[Asset]:
        """Search the visual collection for assets matching an intent."""
        results = self._repo.search_qdrant(
            query_vector=self._embed_query(intent),
            intent=intent.value,
            collection=_VISUAL_COLLECTION,
            top_k=top_k,
        )
        return self._load_assets(results)

    def search_audio(self, intent: Intent, top_k: int = 3) -> list[Asset]:
        """Search the audio collection for SFX matching an intent."""
        results = self._repo.search_qdrant(
            query_vector=self._embed_query(intent),
            intent=intent.value,
            collection=_AUDIO_COLLECTION,
            top_k=top_k,
        )
        return self._load_assets(results)

    def _load_assets(self, qdrant_results: list[dict[str, Any]]) -> list[Asset]:
        assets: list[Asset] = []
        for r in qdrant_results:
            asset = self._repo.get(r["id"])
            if asset:
                assets.append(asset)
        return assets

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def add_asset(
        self,
        file_path: Path,
        kind: AssetKind,
        tags: list[str],
        intent_affinity: list[str],
        description: str | None = None,
        source_url: str | None = None,
        license: str = "owned",
    ) -> Asset:
        """Register a new asset, compute its CLIP embedding, and index in Qdrant.

        Visual assets (images) are encoded with the CLIP *image* encoder so that
        their visual content is searchable.  All other assets (video memes, SFX,
        music) fall back to the CLIP *text* encoder applied to description + tags.

        Args:
            file_path:       Local path to the asset file (must exist).
            kind:            :class:`~autoedit.domain.clip.AssetKind` value.
            tags:            Keyword tags for filtering and display.
            intent_affinity: Intent labels this asset is associated with.
            description:     Optional free-text description.
            source_url:      Canonical URL where the asset was obtained from
                             (used for deduplication in ingestors).
            license:         License identifier (e.g. ``"cc0"``, ``"pixabay"``).

        Returns:
            The created and indexed :class:`~autoedit.domain.asset.Asset`.
        """
        import hashlib

        from autoedit.domain.ids import AssetId, new_id

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Asset file not found: {file_path}")

        sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
        asset = Asset(
            id=AssetId(new_id()),
            kind=kind,
            file_path=str(file_path),
            sha256=sha256,
            tags=tags,
            intent_affinity=intent_affinity,
            description=description,
            source_url=source_url,
            license=license,
        )

        # Persist metadata to SQLite
        self._repo.create(asset)

        # Choose embedding strategy and target collection
        is_visual = kind in _VISUAL_KINDS
        collection = _VISUAL_COLLECTION if is_visual else _AUDIO_COLLECTION

        is_image = file_path.suffix.lower() in _IMAGE_EXTENSIONS
        if is_visual and is_image:
            # Content-based embedding: encode the actual image pixels
            embedding = embed_image(file_path)
            logger.debug(f"[AssetRetrieval] Image-encoded asset {asset.id}")
        else:
            # Description-based embedding: encode text metadata
            meta = description or " ".join(tags + intent_affinity)
            embedding = embed_text(meta)[0]
            logger.debug(f"[AssetRetrieval] Text-encoded asset {asset.id}")

        self._repo.index_in_qdrant(asset, embedding, collection=collection)
        logger.info(f"Asset indexed: {asset.id} ({kind.value}) → {collection}")
        return asset
