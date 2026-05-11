"""Assets repository with SQLite + Qdrant indexing."""

from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient
from sqlmodel import Session, select

from autoedit.domain.clip import Asset, AssetKind
from autoedit.domain.ids import AssetId
from autoedit.settings import settings
from autoedit.storage.db import AssetModel, get_session


class AssetRepository:
    """CRUD for assets with Qdrant indexing."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._own_session = session is None
        self._qdrant: QdrantClient | None = None

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def _qdrant_client(self) -> QdrantClient:
        if self._qdrant is None:
            self._qdrant = QdrantClient(url=settings.QDRANT_URL)
        return self._qdrant

    def create(self, asset: Asset) -> Asset:
        with self._session_ctx() as session:
            model = AssetModel(
                id=asset.id,
                kind=asset.kind.value,
                file_path=asset.file_path,
                sha256=asset.sha256,
                duration_sec=asset.duration_sec,
                width=asset.width,
                height=asset.height,
                sample_rate_hz=asset.sample_rate_hz,
                tags=asset.tags,
                intent_affinity=asset.intent_affinity,
                description=asset.description,
                license=asset.license,
                source_url=asset.source_url,
                added_at=datetime.now(UTC).isoformat(),
            )
            session.add(model)
            session.commit()
            return asset

    def get(self, asset_id: str) -> Asset | None:
        with self._session_ctx() as session:
            model = session.get(AssetModel, asset_id)
            if not model:
                return None
            return self._to_domain(model)

    def list_all(self, kind: AssetKind | None = None) -> list[Asset]:
        with self._session_ctx() as session:
            stmt = select(AssetModel)
            if kind:
                stmt = stmt.where(AssetModel.kind == kind.value)
            results = session.exec(stmt).all()
            return [self._to_domain(r) for r in results]

    def _to_domain(self, model: AssetModel) -> Asset:
        return Asset(
            id=AssetId(model.id),
            kind=AssetKind(model.kind),
            file_path=model.file_path,
            sha256=model.sha256,
            duration_sec=model.duration_sec,
            width=model.width,
            height=model.height,
            sample_rate_hz=model.sample_rate_hz,
            tags=model.tags or [],
            intent_affinity=model.intent_affinity or [],
            description=model.description,
            license=model.license or "owned",
            source_url=model.source_url,
        )

    def index_in_qdrant(
        self,
        asset: Asset,
        embedding: list[float],
        collection: str = "assets_visual",
    ) -> None:
        """Upsert an asset embedding into Qdrant.

        Qdrant requires point IDs to be either unsigned integers or UUIDs.
        Our asset IDs are ULIDs, so we derive a deterministic UUID via
        ``uuid.uuid5(NAMESPACE_OID, ulid_string)`` — same input always produces
        the same UUID, making upserts idempotent.
        The original ULID is stored in the payload under ``asset_id`` so that
        :meth:`search_qdrant` can recover it for SQLite lookups.
        """
        import uuid

        client = self._qdrant_client()
        from qdrant_client.models import PointStruct

        qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_OID, asset.id))
        point = PointStruct(
            id=qdrant_id,
            vector=embedding,
            payload={
                "asset_id": asset.id,          # original ULID for SQLite lookup
                "kind": asset.kind.value,
                "tags": asset.tags,
                "intent_affinity": asset.intent_affinity,
                "description": asset.description,
                "file_path": asset.file_path,
            },
        )
        client.upsert(
            collection_name=collection,
            points=[point],
        )

    def search_qdrant(
        self,
        query_vector: list[float],
        intent: str,
        collection: str = "assets_visual",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search Qdrant for assets matching a query vector and intent."""
        client = self._qdrant_client()
        from qdrant_client.models import FieldCondition, Filter, MatchAny
        query_filter = (
            Filter(
                must=[
                    FieldCondition(
                        key="intent_affinity",
                        match=MatchAny(any=[intent]),
                    )
                ]
            )
            if intent != "other"
            else None
        )
        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        ).points
        return [
            {
                # Prefer the original ULID stored in payload; fall back to Qdrant UUID
                "id": (r.payload or {}).get("asset_id", r.id),
                "score": r.score,
                "payload": r.payload,
            }
            for r in results
        ]
