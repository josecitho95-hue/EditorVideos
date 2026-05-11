"""Basic tests for settings and database initialization."""

from pathlib import Path

from autoedit.settings import Settings, settings
from autoedit.storage.db import get_engine, init_db


def test_settings_data_dir() -> None:
    s = Settings()
    assert isinstance(s.data_dir, Path)


def test_settings_singleton() -> None:
    assert settings is not None
    assert isinstance(settings.db_path, Path)


def test_init_db_creates_file() -> None:
    get_engine()
    init_db()
    assert settings.db_path.exists()
