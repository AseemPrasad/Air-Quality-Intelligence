"""Integration tests for ingestion orchestrator.

Tests complete workflows: watermark progression, deduplication, failure recovery, backfill.
Uses mocked connectors and in-memory SQLite database.
"""

import pytest
import tempfile
import shutil
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

from aq_engine.ingestion.orchestrator import IngestionOrchestrator
from aq_engine.connectors.models import SourceResponse
from aq_engine.common import IngestionFailed


@pytest.fixture
def temp_storage():
    """Temporary storage directory."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aq_test_"))
    yield temp_dir
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def temp_db():
    """Temporary SQLite database URL."""
    return "sqlite:///:memory:"


@pytest.fixture
def temp_config_dir():
    """Temporary config directory with source configs."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aq_config_"))
    sources_dir = temp_dir / "sources"
    sources_dir.mkdir()

    # Create OpenAQ config
    openaq_config = """
openaq:
  name: "OpenAQ API"
  base_url: "https://api.openaq.org/v3"
  timeout_seconds: 30
  rate_limit_per_minute: 60
"""
    (sources_dir / "openaq.yaml").write_text(openaq_config)

    # Create Open-Meteo config
    meteo_config = """
open_meteo:
  name: "Open-Meteo API"
  base_url: "https://api.open-meteo.com/v1"
  timeout_seconds: 30
"""
    (sources_dir / "open_meteo.yaml").write_text(meteo_config)

    yield temp_dir
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def orchestrator(temp_config_dir, temp_storage, temp_db):
    """IngestionOrchestrator with test configuration."""
    return IngestionOrchestrator(
        config_dir=str(temp_config_dir),
        storage_root=str(temp_storage),
        db_url=temp_db,
    )


class TestIngestionWorkflow:
    """Test complete ingestion workflow."""

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_successful_ingestion(self, mock_connector_class, orchestrator):
        """Test successful ingestion: fetch → parse → write → record."""
        # Mock connector
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector

        # Mock API response
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "location": {"id": "123"},
                        "sensor": {"id": "456"},
                        "parameter": {"id": "pm25"},
                        "value": 45.5,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    }
                ],
                "meta": {"total": 1},
            },
            elapsed_seconds=0.5,
            timestamp=datetime.now(timezone.utc),
        )

        # Mock parse
        mock_connector.parse.return_value = [
            {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": 45.5,
                "unit": "µg/m³",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "ingested_at": datetime.now(timezone.utc),
                "raw_payload_hash": "abc123",
            }
        ]

        # Run ingestion
        stats = orchestrator.ingest_source("openaq")

        # Verify stats
        assert stats["status"] == "success"
        assert stats["records_received"] == 1
        assert stats["records_written"] == 1
        assert stats["records_rejected"] == 0
        assert "run_id" in stats
        assert "duration_seconds" in stats

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_watermark_advancement(self, mock_connector_class, orchestrator):
        """Test watermark advances on success, not on failure."""
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector

        # First run: empty watermark, should use lookback
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [], "meta": {"total": 0}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_connector.parse.return_value = []

        stats1 = orchestrator.ingest_source("openaq", lookback_hours=6)
        assert stats1["status"] == "success"

        # Check watermark was recorded
        event_time, ingestion_time = orchestrator.ingestion_repo.get_latest_watermark(1)
        assert event_time is not None

        # Second run: watermark should be used
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [], "meta": {"total": 0}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )

        stats2 = orchestrator.ingest_source("openaq")
        assert stats2["status"] == "success"

        # Verify fetch was called with watermark as start_time
        calls = mock_connector.fetch.call_args_list
        assert len(calls) >= 2
        first_call_start = calls[0][0][0]
        second_call_start = calls[1][0][0]

        # Second call should start from watermark (later than first call)
        assert second_call_start >= first_call_start

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_deduplication(self, mock_connector_class, orchestrator):
        """Test deduplication: ingest twice, same records."""
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector

        record = {
            "source": "openaq",
            "station_id": "123",
            "sensor_id": "456",
            "pollutant": "pm25",
            "value": 45.5,
            "unit": "µg/m³",
            "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "abc123",
        }

        # First ingestion
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [record], "meta": {"total": 1}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_connector.parse.return_value = [record]

        stats1 = orchestrator.ingest_source("openaq")
        assert stats1["records_written"] == 1

        # Second ingestion (same data)
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [record], "meta": {"total": 1}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_connector.parse.return_value = [record]

        stats2 = orchestrator.ingest_source("openaq")
        assert stats2["records_written"] == 1  # Same record deduplicated


class TestFailureRecovery:
    """Test failure handling and recovery."""

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_api_failure_keeps_watermark(self, mock_connector_class, orchestrator):
        """Test API failure: watermark not advanced."""
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector

        # Simulate API error
        mock_connector.fetch.side_effect = IngestionFailed("API error")

        # First successful run to establish watermark
        mock_connector.fetch.side_effect = None
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [], "meta": {"total": 0}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_connector.parse.return_value = []

        orchestrator.ingest_source("openaq")
        event_time1, _ = orchestrator.ingestion_repo.get_latest_watermark(1)

        # Now simulate failure
        mock_connector.fetch.side_effect = IngestionFailed("API error")

        with pytest.raises(IngestionFailed):
            orchestrator.ingest_source("openaq")

        # Watermark should not have advanced
        event_time2, _ = orchestrator.ingestion_repo.get_latest_watermark(1)
        assert event_time2 == event_time1  # Watermark unchanged


class TestBackfill:
    """Test backfill functionality."""

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_backfill_multiple_days(self, mock_connector_class, orchestrator):
        """Test backfill: processes multiple days."""
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector

        # Mock response for any day
        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [], "meta": {"total": 0}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_connector.parse.return_value = []

        # Backfill 3 days
        stats = orchestrator.ingest_source_backfill(
            "openaq",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 15),
        )

        # Should process 3 days
        assert stats["backfill"] is True
        assert stats["days_processed"] == 3
        assert stats["status"] in ("success", "partial")


class TestWatermarkProgression:
    """Test watermark lifecycle."""

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_no_watermark_uses_lookback(self, mock_connector_class, orchestrator):
        """Test that first run uses lookback window."""
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector

        before_call = datetime.now(timezone.utc)

        mock_connector.fetch.return_value = SourceResponse(
            status_code=200,
            headers={},
            body={"results": [], "meta": {"total": 0}},
            elapsed_seconds=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        mock_connector.parse.return_value = []

        orchestrator.ingest_source("openaq", lookback_hours=24)

        # Check fetch was called
        assert mock_connector.fetch.called
        call_args = mock_connector.fetch.call_args[0]
        start_time = call_args[0]

        # Start time should be approximately 24 hours ago
        expected_start = before_call - timedelta(hours=24)
        time_diff = abs((start_time - expected_start).total_seconds())
        assert time_diff < 60  # Within 1 minute


class TestErrorHandling:
    """Test error handling."""

    def test_missing_config_raises_error(self, orchestrator):
        """Test that missing config raises error."""
        with pytest.raises(IngestionFailed, match="Config not found"):
            orchestrator.ingest_source("nonexistent_source")

    @patch("aq_engine.ingestion.orchestrator.OpenAQConnector")
    def test_connector_init_failure(self, mock_connector_class, orchestrator):
        """Test connector initialization failure."""
        mock_connector_class.side_effect = Exception("Connection failed")

        with pytest.raises(IngestionFailed, match="Failed to initialize connector"):
            orchestrator.ingest_source("openaq")


class TestDeduplicationLogic:
    """Test deduplication logic."""

    def test_deduplicate_within_batch(self, orchestrator):
        """Test deduplication within batch."""
        records = [
            {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": 45.5,
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "unit": "µg/m³",
                "ingested_at": datetime.now(timezone.utc),
                "raw_payload_hash": "abc123",
            },
            {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": 45.5,  # Same values
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),  # Same time
                "unit": "µg/m³",
                "ingested_at": datetime.now(timezone.utc),
                "raw_payload_hash": "abc123",
            },
        ]

        deduplicated = orchestrator._deduplicate("openaq", records)

        # Should be deduplicated to 1 record
        assert len(deduplicated) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
