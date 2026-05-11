"""Domain identifiers using ULID."""

from typing import NewType

from ulid import ULID

JobId = NewType("JobId", str)
VodId = NewType("VodId", str)
WindowId = NewType("WindowId", str)
HighlightId = NewType("HighlightId", str)
ClipId = NewType("ClipId", str)
AssetId = NewType("AssetId", str)
EditDecisionId = NewType("EditDecisionId", str)


def new_id() -> str:
    """Generate a new ULID string."""
    return str(ULID())
