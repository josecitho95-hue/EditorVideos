"""Ingestor for SFX from Freesound (https://freesound.org).

Requires a free Freesound API key (FREESOUND_API_KEY in .env).
Get one at: https://freesound.org/apiv2/apply/

Downloads HQ MP3 previews (128 kbps) — publicly accessible without OAuth.
Full-quality download requires OAuth2 (not implemented here; previews are
sufficient for SFX overlays at 24 kHz).

Usage::

    from autoedit.assets.ingest.freesound import run
    from autoedit.assets.retrieval import AssetRetrieval
    added = run(Path("data/assets/sfx"), AssetRetrieval(), api_key="xxx")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from autoedit.assets.retrieval import AssetRetrieval
from autoedit.domain.clip import AssetKind

_BASE_URL = "https://freesound.org/apiv2"
_SEARCH_URL = f"{_BASE_URL}/search/text/"
_FIELDS = "id,name,tags,license,previews,duration,description"

# ---------------------------------------------------------------------------
# Intent → search query mapping
# ---------------------------------------------------------------------------

_INTENT_QUERIES: list[tuple[str, str, list[str]]] = [
    # (query, sfx_tag, intent_affinity)
    ("fail error wrong buzzer", "fail", ["fail"]),
    ("victory win fanfare success", "win", ["win"]),
    ("wow gasp surprise shock", "reaction", ["reaction"]),
    ("rage explosion anger slam", "rage", ["rage"]),
    ("comedy funny cartoon boing pop", "funny", ["funny_moment"]),
    ("applause crowd cheer", "cheer", ["win", "reaction"]),
    ("notification ping ding", "ui", ["reaction", "funny_moment"]),
    ("explosion boom impact", "impact", ["fail", "rage"]),
]


def _known_source_urls(retrieval: AssetRetrieval) -> set[str]:
    return {
        a.source_url
        for a in retrieval._repo.list_all(kind=AssetKind.AUDIO_SFX)
        if a.source_url
    }


def _search(
    query: str,
    api_key: str,
    client: httpx.Client,
    page_size: int = 15,
) -> list[dict[str, Any]]:
    """Run a Freesound text search and return sound records."""
    params = {
        "query": query,
        "token": api_key,
        "fields": _FIELDS,
        "filter": "duration:[0.1 TO 15]",  # max 15s clips for SFX
        "page_size": page_size,
        "sort": "score",
    }
    try:
        resp = client.get(_SEARCH_URL, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as exc:
        logger.warning(f"[freesound] Search failed ({query!r}): {exc}")
        return []


def _download(url: str, dest_path: Path, api_key: str, client: httpx.Client) -> bool:
    """Download preview MP3 (no OAuth required). Returns True on success."""
    try:
        # Freesound preview URLs work without auth — append token just in case
        resp = client.get(
            url,
            params={"token": api_key},
            follow_redirects=True,
            timeout=30,
        )
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(resp.content)
        return True
    except Exception as exc:
        logger.warning(f"[freesound] Download failed {url}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    dest_dir: Path,
    retrieval: AssetRetrieval,
    *,
    api_key: str,
    results_per_query: int = 15,
) -> int:
    """Download and index SFX from Freesound.

    Args:
        dest_dir:           Directory to store downloaded MP3 files.
        retrieval:          :class:`~autoedit.assets.retrieval.AssetRetrieval`
                            instance for registering/indexing.
        api_key:            Freesound API key (FREESOUND_API_KEY).
        results_per_query:  Number of sounds to fetch per intent query.

    Returns:
        Total count of newly added assets.
    """
    known_urls = _known_source_urls(retrieval)
    total = 0

    with httpx.Client(headers={"User-Agent": "autoedit-ai/1.0"}) as client:
        for query, sfx_tag, intent_affinity in _INTENT_QUERIES:
            results = _search(query, api_key, client, page_size=results_per_query)
            logger.info(f"[freesound] Query {query!r}: {len(results)} results")

            for sound in results:
                sound_id: int = sound.get("id", 0)
                name: str = sound.get("name", str(sound_id))
                previews: dict[str, str] = sound.get("previews", {})
                preview_url: str = (
                    previews.get("preview-hq-mp3")
                    or previews.get("preview-lq-mp3")
                    or ""
                )
                if not preview_url:
                    continue

                source_url = f"https://freesound.org/people/sounds/{sound_id}/"
                if source_url in known_urls:
                    continue

                safe_name = re.sub(r"[^\w\-]", "_", name)[:40]
                dest_path = dest_dir / sfx_tag / f"{sfx_tag}_{sound_id}_{safe_name}.mp3"

                if not (dest_path.exists() and dest_path.stat().st_size > 0):
                    if not _download(preview_url, dest_path, api_key, client):
                        continue

                tags = [sfx_tag, "sfx", "freesound"] + sound.get("tags", [])[:5]
                duration: float = float(sound.get("duration", 0.0))

                try:
                    retrieval.add_asset(
                        file_path=dest_path,
                        kind=AssetKind.AUDIO_SFX,
                        tags=tags,
                        intent_affinity=intent_affinity,
                        description=f"Freesound: {name}",
                        source_url=source_url,
                        license="cc",
                    )
                    known_urls.add(source_url)
                    total += 1
                    logger.debug(f"[freesound] +{name} ({duration:.1f}s)")
                except Exception as exc:
                    logger.warning(f"[freesound] Failed to register {name}: {exc}")

    logger.info(f"[freesound] Added {total} new SFX assets")
    return total
