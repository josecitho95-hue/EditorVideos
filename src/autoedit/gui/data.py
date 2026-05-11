"""GUI data-access helpers — thin wrappers over the repository layer."""

from __future__ import annotations

from typing import Any

from autoedit.domain.edit_decision import EditDecision
from autoedit.storage.db import (
    ClipModel,
    EditDecisionModel,
    HighlightModel,
    WindowModel,
    get_session,
    init_db,
)
from autoedit.storage.repositories.assets import AssetRepository
from autoedit.storage.repositories.edit_decisions import EditDecisionRepository
from autoedit.storage.repositories.highlights import HighlightRepository
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.windows import WindowRepository
from sqlmodel import select


def ensure_db() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def list_jobs() -> list[dict[str, Any]]:
    """Return all jobs as plain dicts for the UI."""
    try:
        jobs = JobRepository().list_all()
        return [
            {
                "id": j.id,
                "id_short": j.id[:8],
                "status": j.status.value,
                "stage": j.current_stage.value if j.current_stage else "—",
                "vod_url": (j.vod_url or "")[-60:],
                "created": str(j.created_at)[:16],
            }
            for j in jobs
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def get_job(job_id: str) -> dict[str, Any] | None:
    j = JobRepository().get(job_id)
    if not j:
        return None
    return {
        "id": j.id,
        "status": j.status.value,
        "stage": j.current_stage.value if j.current_stage else "—",
        "vod_url": j.vod_url or "",
        "vod_id": j.vod_id or "",
        "created": str(j.created_at)[:16],
    }


# ---------------------------------------------------------------------------
# Highlights & EditDecisions
# ---------------------------------------------------------------------------

def list_highlights_for_job(job_id: str) -> list[dict[str, Any]]:
    """Return highlights with their edit decisions for a job."""
    highlights = HighlightRepository().list_by_job(job_id, include_discarded=False)
    windows_by_id: dict[str, Any] = {}
    try:
        with get_session() as s:
            rows = s.exec(select(WindowModel).where(WindowModel.job_id == job_id)).all()
            windows_by_id = {r.id: r for r in rows}
    except Exception:
        pass

    decisions_by_hid: dict[str, EditDecision] = {}
    try:
        for ed in EditDecisionRepository().list_by_job(job_id):
            decisions_by_hid[str(ed.highlight_id)] = ed
    except Exception:
        pass

    result = []
    for h in highlights:
        w = windows_by_id.get(str(h.window_id))
        ed = decisions_by_hid.get(str(h.id))
        result.append({
            "id": str(h.id),
            "intent": h.intent.value,
            "confidence": h.triage_confidence,
            "reasoning": h.triage_reasoning or "",
            "window_start": w.start_sec if w else 0.0,
            "window_end": w.end_sec if w else 0.0,
            "window_duration": (w.end_sec - w.start_sec) if w else 0.0,
            "has_decision": ed is not None,
            "title": ed.title if ed else "(sin decisión)",
        })
    return result


def get_edit_decision(highlight_id: str) -> EditDecision | None:
    return EditDecisionRepository().get_by_highlight(highlight_id)


def get_window_for_highlight(highlight_id: str) -> dict[str, float] | None:
    """Return window timing for a highlight."""
    try:
        with get_session() as s:
            h = s.exec(select(HighlightModel).where(HighlightModel.id == highlight_id)).first()
            if not h:
                return None
            w = s.exec(select(WindowModel).where(WindowModel.id == h.window_id)).first()
            if not w:
                return None
            return {"start_sec": w.start_sec, "end_sec": w.end_sec}
    except Exception:
        return None


def save_edit_decision(decision: EditDecision) -> bool:
    """Persist (upsert) an EditDecision. Returns True on success."""
    try:
        repo = EditDecisionRepository()
        with get_session() as s:
            existing = s.exec(
                select(EditDecisionModel).where(
                    EditDecisionModel.highlight_id == str(decision.highlight_id)
                )
            ).first()
            if existing:
                existing.plan = decision.model_dump(mode="json")
                s.add(existing)
                s.commit()
            else:
                from autoedit.settings import settings
                repo.create(decision, model="gui_edit", cost_usd=0.0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def list_assets() -> list[dict[str, Any]]:
    try:
        assets = AssetRepository().list_all()
        return [
            {
                "id": a.id,
                "kind": a.kind.value,
                "description": a.description or "",
                "tags": ", ".join(a.tags[:5]),
                "file": a.file_path,
            }
            for a in assets
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------

def list_clips_for_job(job_id: str) -> list[dict[str, Any]]:
    from pathlib import Path
    try:
        with get_session() as s:
            clips = s.exec(select(ClipModel).where(ClipModel.job_id == job_id)).all()
        return [
            {
                "id": c.id,
                "path": c.output_path,
                "duration": f"{c.duration_sec:.1f}s",
                "size": f"{c.width}×{c.height}",
                "rendered": str(c.rendered_at)[:16],
                "rating": c.user_rating or 0,
                "exists": Path(c.output_path).exists(),
            }
            for c in clips
        ]
    except Exception:
        return []
