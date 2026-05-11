"""Edit decisions repository."""

from datetime import UTC, datetime

from sqlmodel import Session, select

from autoedit.domain.edit_decision import EditDecision
from autoedit.domain.ids import EditDecisionId
from autoedit.storage.db import EditDecisionModel, get_session


class EditDecisionRepository:
    """CRUD for edit decisions."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._own_session = session is None

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def create(self, decision: EditDecision, model: str, cost_usd: float = 0.0) -> EditDecision:
        with self._session_ctx() as session:
            db_model = EditDecisionModel(
                id=EditDecisionId(decision.highlight_id),
                highlight_id=decision.highlight_id,
                plan=decision.model_dump(mode="json"),
                model=model,
                cost_usd=cost_usd,
                created_at=datetime.now(UTC).isoformat(),
            )
            session.add(db_model)
            session.commit()
            return decision

    def get_by_highlight(self, highlight_id: str) -> EditDecision | None:
        with self._session_ctx() as session:
            stmt = select(EditDecisionModel).where(
                EditDecisionModel.highlight_id == highlight_id
            )
            result = session.exec(stmt).first()
            if not result:
                return None
            return EditDecision.model_validate(result.plan)

    def delete_by_job(self, job_id: str) -> int:
        """Delete all edit decisions for a job. Returns count deleted."""
        with self._session_ctx() as session:
            from autoedit.storage.db import HighlightModel
            highlight_ids = set(
                session.exec(
                    select(HighlightModel.id).where(HighlightModel.job_id == job_id)
                ).all()
            )
            if not highlight_ids:
                return 0
            all_decisions = session.exec(select(EditDecisionModel)).all()
            to_delete = [r for r in all_decisions if r.highlight_id in highlight_ids]
            for row in to_delete:
                session.delete(row)
            session.commit()
            return len(to_delete)

    def list_by_job(self, job_id: str) -> list[EditDecision]:
        """List all edit decisions for a job via highlights."""
        with self._session_ctx() as session:
            # Two-step query to avoid SQLAlchemy join typing issues
            from autoedit.storage.db import HighlightModel
            highlight_stmt = select(HighlightModel.id).where(HighlightModel.job_id == job_id)
            highlight_ids = set(session.exec(highlight_stmt).all())

            if not highlight_ids:
                return []

            # Filter EditDecisionModel in Python (avoid IN operator issues)
            stmt = select(EditDecisionModel)
            results = session.exec(stmt).all()
            filtered = [r for r in results if r.highlight_id in highlight_ids]
            return [EditDecision.model_validate(r.plan) for r in filtered]
