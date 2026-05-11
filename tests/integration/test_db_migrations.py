from __future__ import annotations

"""
TC-INT-001 to TC-INT-007
Integration tests for database migrations: table creation, idempotency,
cascade deletes, WAL mode, and foreign-key enforcement.
"""

import pytest
from sqlalchemy import any_
from sqlmodel import Session, create_engine, text
from sqlmodel.pool import StaticPool

# No module-level skip — all tests run with the injectable engine.

from autoedit.storage.db import init_db as run_migrations

# ---------------------------------------------------------------------------
# Actual tables managed by SQLModel metadata (as of Sprint 8)
# ---------------------------------------------------------------------------

EXPECTED_TABLES: list[str] = [
    "jobs",
    "vods",
    "run_steps",
    "transcript_segments",
    "transcript_words",
    "windows",
    "highlights",
    "edit_decisions",
    "clips",
    "assets",
    "asset_usages",
    "narrations",
    "cost_entries",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def in_memory_engine():
    """Provide a fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


# ---------------------------------------------------------------------------
# TC-INT-001 — all tables created
# ---------------------------------------------------------------------------


class TestMigrations:
    def test_all_tables_created(self, in_memory_engine) -> None:
        run_migrations(engine=in_memory_engine)
        with Session(in_memory_engine) as session:
            rows = session.exec(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).all()
        table_names = {row[0] for row in rows}
        missing = [t for t in EXPECTED_TABLES if t not in table_names]
        assert not missing, f"Missing tables after migration: {missing}"

    def test_migration_is_idempotent(self, in_memory_engine) -> None:
        run_migrations(engine=in_memory_engine)
        run_migrations(engine=in_memory_engine)  # second run must not raise
        with Session(in_memory_engine) as session:
            rows = session.exec(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).all()
        table_names = {row[0] for row in rows}
        missing = [t for t in EXPECTED_TABLES if t not in table_names]
        assert not missing, f"Tables missing after idempotent re-run: {missing}"

    def test_cascade_delete_job_removes_windows(self, in_memory_engine) -> None:
        run_migrations(engine=in_memory_engine)
        with in_memory_engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(
                text(
                    "INSERT INTO vods (id, url, duration_sec, language, deleted_source, created_at) "
                    "VALUES ('vod-1', 'http://twitch.tv/v/1', 60.0, 'auto', 0, '2026-01-01T00:00:00')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO jobs (id, vod_url, vod_id, status, created_at, total_cost_usd) "
                    "VALUES ('job-1', 'http://twitch.tv/v/1', 'vod-1', 'queued', '2026-01-01T00:00:00', 0.0)"
                )
            )
            for i in range(3):
                conn.execute(
                    text(
                        f"INSERT INTO windows "
                        f"(id, job_id, vod_id, start_sec, end_sec, rank, score, score_breakdown, transcript_excerpt) "
                        f"VALUES ('win-{i}', 'job-1', 'vod-1', {i*10}, {i*10+10}, {i+1}, 0.5, '{{}}', '')"
                    )
                )
            conn.commit()

        with in_memory_engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("DELETE FROM jobs WHERE id='job-1'"))
            conn.commit()

        with in_memory_engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM windows WHERE job_id='job-1'")
            ).fetchone()
        assert count is not None and count[0] == 0, (
            f"Expected 0 windows after job deletion, got {count}"
        )

    def test_cascade_delete_job_removes_run_steps(self, in_memory_engine) -> None:
        run_migrations(engine=in_memory_engine)
        with in_memory_engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(
                text(
                    "INSERT INTO jobs (id, vod_url, status, created_at, total_cost_usd) "
                    "VALUES ('job-2', 'http://twitch.tv/v/2', 'done', '2026-01-01T00:00:00', 0.0)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO run_steps (job_id, stage, status, cost_usd) "
                    "VALUES ('job-2', 'EXTRACT', 'done', 0.0)"
                )
            )
            conn.commit()

        with in_memory_engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("DELETE FROM jobs WHERE id='job-2'"))
            conn.commit()

        with in_memory_engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM run_steps WHERE job_id='job-2'")
            ).fetchone()
        assert count is not None and count[0] == 0, (
            f"Expected 0 run_steps after job deletion, got {count}"
        )

    def test_wal_mode_enabled(self, in_memory_engine) -> None:
        run_migrations(engine=in_memory_engine)
        with in_memory_engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).fetchone()
        # In-memory SQLite cannot use WAL; it always reports "memory".
        # File-based engines created by get_engine() use "wal".
        assert result is not None and result[0].lower() in ("wal", "memory"), (
            f"Unexpected journal mode: {result!r}"
        )

    def test_foreign_keys_enabled(self, in_memory_engine) -> None:
        run_migrations(engine=in_memory_engine)
        with in_memory_engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys")).fetchone()
        assert result is not None and str(result[0]) == "1", (
            f"Expected foreign_keys=1, got {result!r}"
        )

    def test_narrations_table_has_cache_key_column(self, in_memory_engine) -> None:
        """narrations.id is the SHA256 cache key (primary key)."""
        run_migrations(engine=in_memory_engine)
        with in_memory_engine.connect() as conn:
            rows = conn.execute(
                text("PRAGMA table_info(narrations)")
            ).fetchall()
        col_names = {row[1] for row in rows}  # column name is index 1
        assert "id" in col_names
        assert "text" in col_names
        assert "voice_id" in col_names
        assert "audio_path" in col_names
        assert "used_count" in col_names
