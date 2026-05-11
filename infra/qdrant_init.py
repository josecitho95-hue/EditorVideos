"""Initialize Qdrant collections."""

import sys

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from autoedit.settings import settings


def main():
    client = QdrantClient(url=settings.QDRANT_URL)

    # Visual assets (CLIP ViT-B/32)
    if not client.collection_exists("assets_visual"):
        client.create_collection(
            collection_name="assets_visual",
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        client.create_payload_index(
            collection_name="assets_visual",
            field_name="intent_affinity",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name="assets_visual",
            field_name="tags",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print("Created collection: assets_visual")
    else:
        print("Collection already exists: assets_visual")

    # Audio assets (LAION-CLAP)
    if not client.collection_exists("assets_audio"):
        client.create_collection(
            collection_name="assets_audio",
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        client.create_payload_index(
            collection_name="assets_audio",
            field_name="intent_affinity",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name="assets_audio",
            field_name="tags",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print("Created collection: assets_audio")
    else:
        print("Collection already exists: assets_audio")

    # Transcript chunks (optional, for future RAG)
    if not client.collection_exists("transcript_chunks"):
        client.create_collection(
            collection_name="transcript_chunks",
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        print("Created collection: transcript_chunks")
    else:
        print("Collection already exists: transcript_chunks")

    print("Qdrant initialization complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
