"""Unit tests for IngestionOrchestrator.ingest_source_backfill.

The database and connector are mocked, so these exercise the orchestration only.
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest

from aq_engine.connectors.models import SourceResponse
from aq_engine.ingestion.orchestrator import IngestionOrchestrator


def _response(total: int) -> SourceResponse:
    return SourceResponse(
        status_code=200,
        headers={},
        body={"results": [], "meta": {"total": total}},
        elapsed_seconds=0.0,
        timestamp=datetime.now(timezone.utc),
        raw_payload_hash="hash",
    )


@pytest.fixture
def orchestrator(monkeypatch):
    orch = IngestionOrchestrator.__new__(IngestionOrchestrator)
    orch.ingestion_repo = MagicMock()
    connector = Mock()
    connector.fetch.return_value = _response(total=2)
    connector.parse.return_value = [{"k": 1}, {"k": 2}]
    monkeypatch.setattr(orch, "_load_config", Mock(return_value={}), raising=False)
    monkeypatch.setattr(orch, "_get_source_id", Mock(return_value=7), raising=False)
    monkeypatch.setattr(
        orch, "_init_connector", Mock(return_value=connector), raising=False
    )
    monkeypatch.setattr(
        orch, "_deduplicate", Mock(side_effect=lambda _s, r: r), raising=False
    )
    monkeypatch.setattr(orch, "_write_records", Mock(), raising=False)
    orch.connector = connector
    return orch


def test_helper_methods_belong_to_the_class():
    for name in (
        "ingest_source_backfill",
        "_load_config",
        "_get_source_id",
        "_init_connector",
        "_deduplicate",
        "_write_records",
    ):
        assert callable(getattr(IngestionOrchestrator, name, None)), name


def test_backfill_processes_each_day_and_records_the_run(orchestrator):
    stats = orchestrator.ingest_source_backfill(
        "openaq", date(2026, 8, 13), date(2026, 8, 15)
    )

    assert stats["backfill"] is True
    assert stats["days_processed"] == 3
    assert stats["days_failed"] == 0
    assert stats["total_records_written"] == 6
    assert stats["status"] == "success"
    assert orchestrator.connector.fetch.call_count == 3
    assert orchestrator._write_records.call_args_list[0].args[2] == date(2026, 8, 13)

    orchestrator.ingestion_repo.record_run.assert_called_once()
    recorded = orchestrator.ingestion_repo.record_run.call_args.kwargs
    assert recorded["source_id"] == 7
    assert recorded["status"] == "success"
    assert recorded["records_written"] == 6


def test_a_failed_day_is_counted_and_the_run_is_partial(orchestrator):
    orchestrator.connector.fetch.side_effect = [
        _response(total=2),
        RuntimeError("upstream down"),
        _response(total=2),
    ]

    stats = orchestrator.ingest_source_backfill(
        "openaq", date(2026, 8, 13), date(2026, 8, 15)
    )

    assert stats["days_processed"] == 2
    assert stats["days_failed"] == 1
    assert stats["status"] == "partial"
    assert (
        orchestrator.ingestion_repo.record_run.call_args.kwargs["status"] == "partial"
    )


def test_rejects_an_inverted_date_range(orchestrator):
    with pytest.raises(ValueError, match="Invalid date range"):
        orchestrator.ingest_source_backfill(
            "openaq", date(2026, 8, 15), date(2026, 8, 13)
        )
