"""Voice profile repository — CRUD for registered TTS voice profiles."""

from datetime import UTC, datetime

from loguru import logger
from sqlmodel import Session, select

from autoedit.storage.db import VoiceProfileModel, get_session


class VoiceProfileRepository:
    """CRUD for TTS voice profiles."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def create(
        self,
        voice_id: str,
        display_name: str,
        ref_audio_path: str,
        ref_text: str,
        duration_sec: float,
        sample_rate_hz: int = 24000,
    ) -> VoiceProfileModel:
        """Register a new voice profile (upsert by voice_id)."""
        with self._session_ctx() as session:
            existing = session.get(VoiceProfileModel, voice_id)
            if existing is not None:
                # Update reference audio if re-registered
                existing.display_name = display_name
                existing.ref_audio_path = ref_audio_path
                existing.ref_text = ref_text
                existing.duration_sec = duration_sec
                existing.sample_rate_hz = sample_rate_hz
                existing.created_at = datetime.now(UTC).isoformat()
                session.add(existing)
                session.commit()
                session.refresh(existing)
                logger.info(f"[VoiceRepo] Updated voice profile '{voice_id}'")
                return existing

            profile = VoiceProfileModel(
                id=voice_id,
                display_name=display_name,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                duration_sec=duration_sec,
                sample_rate_hz=sample_rate_hz,
                created_at=datetime.now(UTC).isoformat(),
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            logger.info(f"[VoiceRepo] Registered voice profile '{voice_id}'")
            return profile

    def get(self, voice_id: str) -> VoiceProfileModel | None:
        """Return a voice profile by ID, or None if not found."""
        with self._session_ctx() as session:
            return session.get(VoiceProfileModel, voice_id)

    def list_all(self) -> list[VoiceProfileModel]:
        """Return all registered voice profiles."""
        with self._session_ctx() as session:
            return list(session.exec(select(VoiceProfileModel)).all())

    def delete(self, voice_id: str) -> bool:
        """Delete a voice profile. Returns True if it existed."""
        with self._session_ctx() as session:
            profile = session.get(VoiceProfileModel, voice_id)
            if profile is None:
                return False
            session.delete(profile)
            session.commit()
            logger.info(f"[VoiceRepo] Deleted voice profile '{voice_id}'")
            return True
