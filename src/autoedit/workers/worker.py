"""arq worker settings."""

from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from autoedit.settings import settings
from autoedit.workers.tasks import process_job


async def startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook."""
    pass


async def shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook."""
    pass


class WorkerSettings:
    """arq worker configuration."""

    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [process_job]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 1  # Sequential GPU processing
    job_timeout = 7200  # 2 hours


async def get_redis() -> Any:
    """Get a redis pool for enqueuing."""
    return await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
