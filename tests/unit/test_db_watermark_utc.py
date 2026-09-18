"""get_latest_watermark must return timezone-aware UTC datetimes."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from aq_engine.storage.db import IngestionRunRepository


def _repo_returning(run):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (
        run
    )

    @contextmanager
    def fake_session():
        yield session

    db = SimpleNamespace(session=fake_session)
    return IngestionRunRepository(db)


def test_naive_values_from_the_database_come_back_as_utc():
    """SQLite drops tzinfo from DateTime(timezone=True) columns."""
    run = SimpleNamespace(
        requested_end=datetime(2026, 8, 15, 12, 0),
        finished_at=datetime(2026, 8, 15, 12, 5),
    )

    event_time, ingestion_time = _repo_returning(run).get_latest_watermark(1)

    assert event_time == datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    assert ingestion_time == datetime(2026, 8, 15, 12, 5, tzinfo=timezone.utc)
    # The orchestrator compares the watermark with aware times.
    assert event_time < datetime.now(timezone.utc)


def test_missing_finished_at_stays_none():
    run = SimpleNamespace(requested_end=datetime(2026, 8, 15, 12, 0), finished_at=None)

    event_time, ingestion_time = _repo_returning(run).get_latest_watermark(1)

    assert event_time.tzinfo is not None
    assert ingestion_time is None


def test_no_successful_run_returns_none():
    assert _repo_returning(None).get_latest_watermark(1) == (None, None)
