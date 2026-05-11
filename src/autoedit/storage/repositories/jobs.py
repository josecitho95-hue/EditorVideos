"""Jobs repository."""

from datetime import UTC, datetime

from sqlmodel import Session, select

from autoedit.domain.ids import JobId, VodId
from autoedit.domain.job import Job, JobConfig, JobStatus, Stage
from autoedit.storage.db import JobModel, get_session


def _to_domain(model: JobModel) -> Job:
    return Job(
        id=JobId(model.id),
        vod_url=model.vod_url,
        vod_id=VodId(model.vod_id) if model.vod_id else None,
        status=JobStatus(model.status),
        current_stage=Stage(model.current_stage) if model.current_stage else None,
        config=JobConfig.model_validate(model.config),
        error=model.error,
        created_at=datetime.fromisoformat(model.created_at),
        started_at=datetime.fromisoformat(model.started_at) if model.started_at else None,
        finished_at=datetime.fromisoformat(model.finished_at) if model.finished_at else None,
        total_cost_usd=model.total_cost_usd,
    )


class JobRepository:
    """CRUD for jobs."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._own_session = session is None

    def _session_ctx(self) -> Session:
        if self._session is not None:
            return self._session
        return get_session()

    def create(self, job: Job) -> Job:
        with self._session_ctx() as session:
            model = JobModel(
                id=job.id,
                vod_url=job.vod_url,
                vod_id=job.vod_id,
                status=job.status.value,
                current_stage=job.current_stage.value if job.current_stage else None,
                config=job.config.model_dump(mode="json"),
                error=job.error,
                created_at=job.created_at.isoformat(),
                started_at=job.started_at.isoformat() if job.started_at else None,
                finished_at=job.finished_at.isoformat() if job.finished_at else None,
                total_cost_usd=job.total_cost_usd,
            )
            session.add(model)
            session.commit()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._session_ctx() as session:
            model = session.get(JobModel, job_id)
            if not model:
                return None
            return _to_domain(model)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        stage: Stage | None = None,
        error: str | None = None,
    ) -> None:
        with self._session_ctx() as session:
            model = session.get(JobModel, job_id)
            if not model:
                return
            model.status = status.value
            if stage:
                model.current_stage = stage.value
            if error is not None:
                model.error = error
            if status == JobStatus.RUNNING and not model.started_at:
                model.started_at = datetime.now(UTC).isoformat()
            if status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                model.finished_at = datetime.now(UTC).isoformat()
            session.add(model)
            session.commit()

    def update_vod_id(self, job_id: str, vod_id: VodId) -> None:
        with self._session_ctx() as session:
            model = session.get(JobModel, job_id)
            if not model:
                return
            model.vod_id = vod_id
            session.add(model)
            session.commit()

    def list_all(self, status: JobStatus | None = None) -> list[Job]:
        with self._session_ctx() as session:
            stmt = select(JobModel)
            if status:
                stmt = stmt.where(JobModel.status == status.value)
            from sqlalchemy import desc
            stmt = stmt.order_by(desc(JobModel.created_at))
            results = session.exec(stmt).all()
            return [_to_domain(r) for r in results]
