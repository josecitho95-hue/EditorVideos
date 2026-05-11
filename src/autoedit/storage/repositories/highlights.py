"""Highlights repository."""

from sqlmodel import Session, select

from autoedit.domain.highlight import Highlight, Intent
from autoedit.domain.ids import HighlightId, JobId, WindowId
from autoedit.storage.db import HighlightModel, get_session


class HighlightRepository:
    """CRUD for highlights."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._own_session = session is None

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def create(self, highlight: Highlight) -> None:
        with self._session_ctx() as session:
            model = HighlightModel(
                id=highlight.id,
                window_id=highlight.window_id,
                job_id=highlight.job_id,
                intent=highlight.intent.value,
                triage_confidence=highlight.triage_confidence,
                triage_reasoning=highlight.triage_reasoning,
                discarded=1 if highlight.discarded else 0,
                discard_reason=highlight.discard_reason,
            )
            session.add(model)
            session.commit()

    def create_many(self, highlights: list[Highlight]) -> None:
        with self._session_ctx() as session:
            for highlight in highlights:
                model = HighlightModel(
                    id=highlight.id,
                    window_id=highlight.window_id,
                    job_id=highlight.job_id,
                    intent=highlight.intent.value,
                    triage_confidence=highlight.triage_confidence,
                    triage_reasoning=highlight.triage_reasoning,
                    discarded=1 if highlight.discarded else 0,
                    discard_reason=highlight.discard_reason,
                )
                session.add(model)
            session.commit()

    def list_by_job(self, job_id: str, include_discarded: bool = False) -> list[Highlight]:
        with self._session_ctx() as session:
            stmt = select(HighlightModel).where(HighlightModel.job_id == job_id)
            if not include_discarded:
                stmt = stmt.where(HighlightModel.discarded == 0)
            results = session.exec(stmt).all()
            return [
                Highlight(
                    id=HighlightId(r.id),
                    window_id=WindowId(r.window_id),
                    job_id=JobId(r.job_id),
                    intent=Intent(r.intent),
                    triage_confidence=r.triage_confidence,
                    triage_reasoning=r.triage_reasoning or "",
                    discarded=bool(r.discarded),
                    discard_reason=r.discard_reason,
                )
                for r in results
            ]

    def get(self, highlight_id: str) -> Highlight | None:
        with self._session_ctx() as session:
            model = session.get(HighlightModel, highlight_id)
            if not model:
                return None
            return Highlight(
                id=HighlightId(model.id),
                window_id=WindowId(model.window_id),
                job_id=JobId(model.job_id),
                intent=Intent(model.intent),
                triage_confidence=model.triage_confidence,
                triage_reasoning=model.triage_reasoning or "",
                discarded=bool(model.discarded),
                discard_reason=model.discard_reason,
            )
