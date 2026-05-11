"""Windows repository."""

from sqlmodel import Session, select

from autoedit.domain.ids import VodId, WindowId
from autoedit.domain.signals import WindowCandidate
from autoedit.storage.db import WindowModel, get_session


class WindowRepository:
    """CRUD for window candidates."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._own_session = session is None

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def create(self, window: WindowCandidate) -> None:
        with self._session_ctx() as session:
            model = WindowModel(
                id=window.id,
                job_id="",  # Will be set by caller if needed
                vod_id=window.vod_id,
                start_sec=window.start_sec,
                end_sec=window.end_sec,
                score=window.score,
                score_breakdown=window.score_breakdown,
                rank=window.rank,
            )
            session.add(model)
            session.commit()

    def create_many(self, windows: list[WindowCandidate], job_id: str) -> None:
        with self._session_ctx() as session:
            for window in windows:
                model = WindowModel(
                    id=window.id,
                    job_id=job_id,
                    vod_id=window.vod_id,
                    start_sec=window.start_sec,
                    end_sec=window.end_sec,
                    score=window.score,
                    score_breakdown=window.score_breakdown,
                    rank=window.rank,
                )
                session.add(model)
            session.commit()

    def list_by_job(self, job_id: str) -> list[WindowCandidate]:
        with self._session_ctx() as session:
            from sqlalchemy import desc
            stmt = select(WindowModel).where(WindowModel.job_id == job_id).order_by(desc("rank"))
            results = session.exec(stmt).all()
            return [
                WindowCandidate(
                    id=WindowId(r.id),
                    vod_id=VodId(r.vod_id),
                    start_sec=r.start_sec,
                    end_sec=r.end_sec,
                    score=r.score,
                    score_breakdown=r.score_breakdown,
                    rank=r.rank,
                    transcript_excerpt="",
                )
                for r in results
            ]
