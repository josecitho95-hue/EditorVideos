"""Ingestor for Twitch emotes from BTTV, 7TV and FFZ.

All three APIs are public — no API key required.

Sources
-------
- BTTV global: https://api.betterttv.net/3/cached/emotes/global
- 7TV global:  https://7tv.io/v3/emote-sets/global
- FFZ global:  https://api.frankerfacez.com/v1/set/global

Assets are stored as :attr:`~autoedit.domain.clip.AssetKind.VISUAL_IMAGE`
with intent_affinity inferred from emote name patterns.

Usage::

    from autoedit.assets.ingest.twitch_emotes import run
    from autoedit.assets.retrieval import AssetRetrieval
    dest = Path("data/assets/emotes")
    added = run(dest, AssetRetrieval())
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from autoedit.assets.retrieval import AssetRetrieval
from autoedit.domain.clip import AssetKind

# ---------------------------------------------------------------------------
# Intent affinity patterns (matched against emote code, case-insensitive)
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: list[tuple[re.Pattern[str], list[str]]] = [
    # Win / hype
    (re.compile(r"pog|poggers|hypers|godlike|Winner|clutch", re.I), ["win", "reaction"]),
    # Funny
    (re.compile(r"lul|kek|4head|haha|xd|clown|pepega|omegalul|lmao", re.I), ["funny_moment"]),
    # Fail / bad
    (re.compile(r"fail|bad|wrong|rip|sadge|feelsbad|pepehands|d:", re.I), ["fail"]),
    # Rage
    (re.compile(r"rage|tilt|mad|angry|bttv|reeee|triggered", re.I), ["rage"]),
    # Wholesome
    (re.compile(r"love|heart|wholesome|cute|peepo.*heart|comfy", re.I), ["wholesome"]),
    # Reaction / surprise
    (re.compile(r"monka|gasp|wow|shocked|eyes|peepo|omg|wtf", re.I), ["reaction"]),
    # Skill
    (re.compile(r"ez|easy|skill|pro|gg|boomer", re.I), ["skill_play"]),
]


def _intent_for_code(code: str) -> list[str]:
    """Return intent_affinity tags for an emote based on its name/code."""
    for pattern, intents in _INTENT_PATTERNS:
        if pattern.search(code):
            return intents
    # Default: react + funny (most emotes fit this bucket)
    return ["reaction", "funny_moment"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _known_source_urls(retrieval: AssetRetrieval) -> set[str]:
    """Return the set of source_urls already in the asset catalog."""
    return {
        a.source_url
        for a in retrieval._repo.list_all(kind=AssetKind.VISUAL_IMAGE)
        if a.source_url
    }


def _download_emote(
    url: str,
    dest_path: Path,
    client: httpx.Client,
) -> bool:
    """Download *url* to *dest_path*. Returns True on success."""
    try:
        resp = client.get(url, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(resp.content)
        return True
    except Exception as exc:
        logger.warning(f"[emotes] Download failed {url}: {exc}")
        return False


def _register(
    file_path: Path,
    source_url: str,
    code: str,
    tags: list[str],
    retrieval: AssetRetrieval,
) -> bool:
    """Register a downloaded emote file. Returns True if newly added."""
    try:
        retrieval.add_asset(
            file_path=file_path,
            kind=AssetKind.VISUAL_IMAGE,
            tags=["emote", code, *tags],
            intent_affinity=_intent_for_code(code),
            description=f"Twitch emote: {code}",
            source_url=source_url,
            license="cc0",
        )
        return True
    except Exception as exc:
        logger.warning(f"[emotes] Failed to register {code}: {exc}")
        return False


# ---------------------------------------------------------------------------
# BTTV
# ---------------------------------------------------------------------------

_BTTV_GLOBAL_URL = "https://api.betterttv.net/3/cached/emotes/global"
_BTTV_CDN = "https://cdn.betterttv.net/emote/{id}/2x"


def _ingest_bttv(
    dest_dir: Path,
    retrieval: AssetRetrieval,
    known_urls: set[str],
    client: httpx.Client,
    limit: int,
) -> int:
    """Ingest BTTV global emotes. Returns count of new assets."""
    added = 0
    try:
        resp = client.get(_BTTV_GLOBAL_URL, timeout=15)
        resp.raise_for_status()
        emotes: list[dict[str, Any]] = resp.json()
    except Exception as exc:
        logger.error(f"[emotes:bttv] API call failed: {exc}")
        return 0

    logger.info(f"[emotes:bttv] {len(emotes)} global emotes available")

    for emote in emotes[:limit]:
        emote_id: str = emote.get("id", "")
        code: str = emote.get("code", emote_id)
        image_type: str = emote.get("imageType", "png")

        url = _BTTV_CDN.format(id=emote_id)
        if url in known_urls:
            continue

        ext = ".gif" if image_type == "gif" else ".png"
        safe_code = re.sub(r"[^\w\-]", "_", code)
        dest_path = dest_dir / "bttv" / f"{safe_code}_{emote_id}{ext}"

        if dest_path.exists() and dest_path.stat().st_size > 0:
            pass  # already on disk, just re-register
        elif not _download_emote(url, dest_path, client):
            continue

        if _register(dest_path, url, code, ["bttv"], retrieval):
            known_urls.add(url)
            added += 1
            logger.debug(f"[emotes:bttv] +{code}")

    logger.info(f"[emotes:bttv] Added {added} new emotes")
    return added


# ---------------------------------------------------------------------------
# 7TV
# ---------------------------------------------------------------------------

_7TV_GLOBAL_URL = "https://7tv.io/v3/emote-sets/global"
_7TV_CDN = "https://cdn.7tv.app/emote/{id}/2x.webp"


def _ingest_7tv(
    dest_dir: Path,
    retrieval: AssetRetrieval,
    known_urls: set[str],
    client: httpx.Client,
    limit: int,
) -> int:
    """Ingest 7TV global emotes. Returns count of new assets."""
    added = 0
    try:
        resp = client.get(_7TV_GLOBAL_URL, timeout=15)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except Exception as exc:
        logger.error(f"[emotes:7tv] API call failed: {exc}")
        return 0

    emotes: list[dict[str, Any]] = data.get("emotes", [])
    logger.info(f"[emotes:7tv] {len(emotes)} global emotes available")

    for emote in emotes[:limit]:
        emote_id: str = emote.get("id", "")
        code: str = emote.get("name", emote_id)

        url = _7TV_CDN.format(id=emote_id)
        if url in known_urls:
            continue

        safe_code = re.sub(r"[^\w\-]", "_", code)
        dest_path = dest_dir / "7tv" / f"{safe_code}_{emote_id}.webp"

        if not (dest_path.exists() and dest_path.stat().st_size > 0):
            if not _download_emote(url, dest_path, client):
                continue

        if _register(dest_path, url, code, ["7tv"], retrieval):
            known_urls.add(url)
            added += 1
            logger.debug(f"[emotes:7tv] +{code}")

    logger.info(f"[emotes:7tv] Added {added} new emotes")
    return added


# ---------------------------------------------------------------------------
# FFZ
# ---------------------------------------------------------------------------

_FFZ_GLOBAL_URL = "https://api.frankerfacez.com/v1/set/global"


def _ingest_ffz(
    dest_dir: Path,
    retrieval: AssetRetrieval,
    known_urls: set[str],
    client: httpx.Client,
    limit: int,
) -> int:
    """Ingest FFZ global emotes. Returns count of new assets."""
    added = 0
    try:
        resp = client.get(_FFZ_GLOBAL_URL, timeout=15)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except Exception as exc:
        logger.error(f"[emotes:ffz] API call failed: {exc}")
        return 0

    sets: dict[str, Any] = data.get("sets", {})
    emotes: list[dict[str, Any]] = []
    for s in sets.values():
        emotes.extend(s.get("emoticons", []))

    logger.info(f"[emotes:ffz] {len(emotes)} global emotes available")

    for emote in emotes[:limit]:
        code: str = str(emote.get("name", ""))
        urls: dict[str, str] = emote.get("urls", {})
        # prefer 2x, fall back to 1x or 4x
        url = urls.get("2") or urls.get("1") or urls.get("4") or ""
        if not url:
            continue
        if not url.startswith("http"):
            url = "https:" + url
        if url in known_urls:
            continue

        safe_code = re.sub(r"[^\w\-]", "_", code)
        emote_id = str(emote.get("id", ""))
        dest_path = dest_dir / "ffz" / f"{safe_code}_{emote_id}.png"

        if not (dest_path.exists() and dest_path.stat().st_size > 0):
            if not _download_emote(url, dest_path, client):
                continue

        if _register(dest_path, url, code, ["ffz"], retrieval):
            known_urls.add(url)
            added += 1
            logger.debug(f"[emotes:ffz] +{code}")

    logger.info(f"[emotes:ffz] Added {added} new emotes")
    return added


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    dest_dir: Path,
    retrieval: AssetRetrieval,
    *,
    limit_per_source: int = 200,
    sources: list[str] | None = None,
) -> int:
    """Download and index global Twitch emotes from BTTV, 7TV and FFZ.

    Args:
        dest_dir:         Root directory to store emote images.
        retrieval:        :class:`~autoedit.assets.retrieval.AssetRetrieval`
                          instance used to register and index assets.
        limit_per_source: Maximum number of emotes to ingest per source API.
        sources:          Subset of sources to run (``["bttv", "7tv", "ffz"]``).
                          Defaults to all three.

    Returns:
        Total count of newly added assets.
    """
    active = set(sources or ["bttv", "7tv", "ffz"])
    known_urls = _known_source_urls(retrieval)
    total = 0

    with httpx.Client(headers={"User-Agent": "autoedit-ai/1.0"}) as client:
        if "bttv" in active:
            total += _ingest_bttv(dest_dir, retrieval, known_urls, client, limit_per_source)
        if "7tv" in active:
            total += _ingest_7tv(dest_dir, retrieval, known_urls, client, limit_per_source)
        if "ffz" in active:
            total += _ingest_ffz(dest_dir, retrieval, known_urls, client, limit_per_source)

    return total
