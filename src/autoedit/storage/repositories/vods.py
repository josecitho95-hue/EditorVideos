"""Vods repository."""

from datetime import UTC, datetime

from sqlmodel import Session

from autoedit.domain.ids import VodId
from autoedit.storage.db import VodModel, get_session


class VodRepository:
    """CRUD for VODs."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._own_session = session is None

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def create(
        self,
        vod_id: VodId,
        url: str,
        title: str | None,
        streamer: str | None,
        duration_sec: float,
        recorded_at: str | None,
        language: str,
        source_path: str | None,
        source_size_mb: float | None,
    ) -> None:
        with self._session_ctx() as session:
            model = VodModel(
                id=vod_id,
                url=url,
                title=title,
                streamer=streamer,
                duration_sec=duration_sec,
                recorded_at=recorded_at,
                language=language,
                source_path=source_path,
                source_size_mb=source_size_mb,
                created_at=datetime.now(UTC).isoformat(),
            )
            session.add(model)
            session.commit()

    def get(self, vod_id: str) -> VodModel | None:
        with self._session_ctx() as session:
            return session.get(VodModel, vod_id)

    def update_paths(
        self,
        vod_id: str,
        audio_path: str | None = None,
        chat_path: str | None = None,
    ) -> None:
        with self._session_ctx() as session:
            model = session.get(VodModel, vod_id)
            if not model:
                return
            if audio_path:
                model.audio_path = audio_path
            if chat_path:
                model.chat_path = chat_path
            session.add(model)
            session.commit()

    def mark_deleted(self, vod_id: str) -> None:
        with self._session_ctx() as session:
            model = session.get(VodModel, vod_id)
            if model:
                model.deleted_source = 1
                session.add(model)
                session.commit()
