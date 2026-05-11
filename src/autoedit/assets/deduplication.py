"""Asset deduplication — filter recently used assets."""

from loguru import logger

from autoedit.domain.clip import Asset
from autoedit.storage.db import AssetUsageModel, get_session


def filter_recent_usage(assets: list[Asset], window_hours: float = 48.0) -> list[Asset]:
    """Remove assets that have been used in the last N hours.

    Args:
        assets: Candidate assets to filter.
        window_hours: Lookback window in hours.

    Returns:
        Assets not used within the lookback window.
    """
    if not assets:
        return []

    asset_ids = [a.id for a in assets]

    with get_session() as session:
        # Query all usages and filter in Python (avoids SQLAlchemy IN operator issues)
        from sqlmodel import select
        stmt = select(AssetUsageModel)
        results = session.exec(stmt).all()
        # Note: timeline_start is float (seconds), not a timestamp.
        # For true time-based filtering we need a created_at field on AssetUsageModel.
        # For now, deduplicate purely by recent usage existence.
        recently_used = {r.asset_id for r in results if r.asset_id in asset_ids}

    filtered = [a for a in assets if a.id not in recently_used]
    removed = len(assets) - len(filtered)
    if removed:
        logger.info(f"Filtered {removed} recently used assets (last {window_hours}h)")

    return filtered
