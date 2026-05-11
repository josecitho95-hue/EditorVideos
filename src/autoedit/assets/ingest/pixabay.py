"""Ingestor for images from Pixabay (https://pixabay.com).

Requires a free Pixabay API key (PIXABAY_API_KEY in .env).
Get one at: https://pixabay.com/api/docs/#api_key

Downloads small-to-medium sized WebP/JPG images (web format, ≤ 640px)
suitable for meme overlays and reaction image backgrounds.
Full-resolution download requires Pixabay terms compliance (attribution
not required but accreditation recommended).

Usage::

    from autoedit.assets.ingest.pixabay import run
    from autoedit.assets.retrieval import AssetRetrieval
    added = run(Path("data/assets/images"), AssetRetrieval(), api_key="xxx")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from autoedit.assets.retrieval import AssetRetrieval
from autoedit.domain.clip import AssetKind

_API_URL = "https://pixabay.com/api/"

# ---------------------------------------------------------------------------
# Intent → query mapping (images)
# ---------------------------------------------------------------------------

_INTENT_QUERIES: list[tuple[str, str, list[str]]] = [
    # (search query,  category_tag,  intent_affinity)
    ("gaming controller joystick", "gaming", ["skill_play", "win"]),
    ("explosion fire boom", "explosion", ["fail", "rage"]),
    ("trophy victory gold", "trophy", ["win"]),
    ("fail mistake oops", "fail", ["fail", "funny_moment"]),
    ("meme funny reaction face", "meme", ["funny_moment", "reaction"]),
    ("rage angry fist", "rage", ["rage"]),
    ("celebration confetti party", "celebrate", ["win", "wholesome"]),
    ("shocked surprised gasp", "shocked", ["reaction"]),
    ("gaming streamer esports", "esports", ["skill_play"]),
    ("emoji sticker reaction", "sticker", ["reaction", "funny_moment"]),
]


def _known_source_urls(retrieval: AssetRetrieval) -> set[str]:
    return {
        a.source_url
        for a in retrieval._repo.list_all(kind=AssetKind.VISUAL_IMAGE)
        if a.source_url
    }


def _search(
    query: str,
    api_key: str,
    client: httpx.Client,
    per_page: int = 20,
    image_type: str = "all",
) -> list[dict[str, Any]]:
    """Query Pixabay API and return image records."""
    params = {
        "key": api_key,
        "q": query,
        "image_type": image_type,
        "per_page": per_page,
        "safesearch": "true",
        "editors_choice": "false",
    }
    try:
        resp = client.get(_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json().get("hits", [])
    except Exception as exc:
        logger.warning(f"[pixabay] Search failed ({query!r}): {exc}")
        return []


def _download(url: str, dest_path: Path, client: httpx.Client) -> bool:
    """Download image to dest_path. Returns True on success."""
    try:
        resp = client.get(url, follow_redirects=True, timeout=20)
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(resp.content)
        return True
    except Exception as exc:
        logger.warning(f"[pixabay] Download failed {url}: {exc}")
        return False


def _ext_from_url(url: str) -> str:
    parts = url.split(".")
    if parts:
        ext = parts[-1].split("?")[0].lower()
        if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
            return f".{ext}"
    return ".jpg"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    dest_dir: Path,
    retrieval: AssetRetrieval,
    *,
    api_key: str,
    results_per_query: int = 20,
) -> int:
    """Download and index images from Pixabay.

    Downloads the ``webformatURL`` version (≤ 640px, WebP/JPG) — small
    enough to overlay over clips without impacting render performance.

    Args:
        dest_dir:           Directory to store downloaded images.
        retrieval:          :class:`~autoedit.assets.retrieval.AssetRetrieval`
                            instance for registering/indexing.
        api_key:            Pixabay API key (PIXABAY_API_KEY).
        results_per_query:  Images to fetch per intent query (max 200).

    Returns:
        Total count of newly added assets.
    """
    known_urls = _known_source_urls(retrieval)
    total = 0

    with httpx.Client(headers={"User-Agent": "autoedit-ai/1.0"}) as client:
        for query, category_tag, intent_affinity in _INTENT_QUERIES:
            hits = _search(
                query,
                api_key,
                client,
                per_page=min(results_per_query, 200),
            )
            logger.info(f"[pixabay] Query {query!r}: {len(hits)} results")

            for hit in hits:
                image_id: int = hit.get("id", 0)
                page_url: str = hit.get("pageURL", "")
                img_url: str = hit.get("webformatURL", "")
                tags_str: str = hit.get("tags", "")
                width: int = hit.get("webformatWidth", 0)
                height: int = hit.get("webformatHeight", 0)

                if not img_url:
                    continue
                source_url = page_url or img_url
                if source_url in known_urls:
                    continue

                ext = _ext_from_url(img_url)
                safe_query = re.sub(r"[^\w]", "_", query)[:20]
                dest_path = dest_dir / category_tag / f"{category_tag}_{image_id}{ext}"

                if not (dest_path.exists() and dest_path.stat().st_size > 0):
                    if not _download(img_url, dest_path, client):
                        continue

                tags = [category_tag, "pixabay"]
                if tags_str:
                    tags += [t.strip() for t in tags_str.split(",")][:4]

                try:
                    retrieval.add_asset(
                        file_path=dest_path,
                        kind=AssetKind.VISUAL_IMAGE,
                        tags=tags,
                        intent_affinity=intent_affinity,
                        description=f"Pixabay: {query} ({image_id})",
                        source_url=source_url,
                        license="pixabay",
                    )
                    known_urls.add(source_url)
                    total += 1
                    logger.debug(f"[pixabay] +{category_tag}/{image_id} ({width}x{height})")
                except Exception as exc:
                    logger.warning(f"[pixabay] Failed to register {image_id}: {exc}")

    logger.info(f"[pixabay] Added {total} new image assets")
    return total
