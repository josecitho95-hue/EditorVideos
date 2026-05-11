"""Tests for domain identifiers."""

from autoedit.domain.ids import new_id


def test_new_id_is_ulid() -> None:
    uid = new_id()
    assert isinstance(uid, str)
    assert len(uid) == 26


def test_new_id_unique() -> None:
    ids = {new_id() for _ in range(100)}
    assert len(ids) == 100
