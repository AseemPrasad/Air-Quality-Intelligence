"""Unit tests for quarantine handling.

Tests quarantine storage, reading, and statistics for invalid/suspicious records.
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timezone

from aq_engine.quality.quarantine import QuarantineManager


@pytest.fixture
def temp_quarantine_root():
    """Temporary quarantine root directory."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aq_quarantine_test_"))
    yield temp_dir
    # Cleanup
    if temp_dir.exists():
        import shutil
        shutil.rmtree(temp_dir)


@pytest.fixture
def quarantine_manager(temp_quarantine_root):
    """QuarantineManager with temporary storage."""
    return QuarantineManager(quarantine_root=str(temp_quarantine_root))


@pytest.fixture
def invalid_aq_records():
    """Sample invalid air quality records."""
    return [
        (
            {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": -5.0,  # Invalid: negative
                "unit": "µg/m³",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": "abc123",
            },
            ["Pollutant value must be non-negative"],
        ),
        (
            {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": 45.5,
                "unit": "µg/m³",
                "observed_at": None,  # Invalid: null required field
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": "abc123",
            },
            ["Null required field: observed_at"],
        ),
    ]


@pytest.fixture
def suspicious_aq_records():
    """Sample suspicious air quality records."""
    return [
        (
            {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": 50.0,  # Suspicious: round number
                "unit": "µg/m³",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": "abc123",
            },
            ["Value is suspiciously round (possible default)"],
        ),
    ]


class TestQuarantineInvalidRecords:
    """Test quarantine handling for invalid records."""

    def test_quarantine_invalid_records_creates_file(
        self, quarantine_manager, invalid_aq_records
    ):
        """Test quarantine creates JSONL file."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )

        # Check file exists
        quarantine_files = list(
            (quarantine_manager.quarantine_root / "openaq").glob("**/*.jsonl")
        )
        assert len(quarantine_files) > 0

    def test_quarantine_invalid_records_preserves_data(
        self, quarantine_manager, invalid_aq_records
    ):
        """Test quarantine preserves record data."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )

        records = quarantine_manager.read_quarantine_records("openaq", "invalid")
        assert len(records) >= 2

        # Check first record preserved
        assert records[0]["value"] == -5.0
        assert records[0]["station_id"] == "123"

    def test_quarantine_adds_metadata(self, quarantine_manager, invalid_aq_records):
        """Test quarantine adds rejection metadata."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )

        records = quarantine_manager.read_quarantine_records("openaq", "invalid")
        for record in records:
            assert "quarantine_timestamp" in record
            assert "rejection_reasons" in record
            assert "record_type" in record
            assert record["record_type"] == "air_quality"
            assert len(record["rejection_reasons"]) > 0

    def test_quarantine_empty_list_no_file(self, quarantine_manager):
        """Test empty list doesn't create file."""
        quarantine_manager.quarantine_invalid_records("openaq", [], record_type="air_quality")

        quarantine_files = list(
            (quarantine_manager.quarantine_root / "openaq").glob("*/*/**.jsonl")
        )
        assert len(quarantine_files) == 0


class TestQuarantineSuspiciousRecords:
    """Test quarantine handling for suspicious records."""

    def test_quarantine_suspicious_records_creates_file(
        self, quarantine_manager, suspicious_aq_records
    ):
        """Test suspicious quarantine creates JSONL file."""
        quarantine_manager.quarantine_suspicious_records(
            "openaq", suspicious_aq_records, record_type="air_quality"
        )

        quarantine_files = list(
            (quarantine_manager.quarantine_root / "openaq" / "suspicious").glob("**/*.jsonl")
        )
        assert len(quarantine_files) > 0

    def test_quarantine_suspicious_adds_warning_tags(
        self, quarantine_manager, suspicious_aq_records
    ):
        """Test suspicious records have warning tags."""
        quarantine_manager.quarantine_suspicious_records(
            "openaq", suspicious_aq_records, record_type="air_quality"
        )

        records = quarantine_manager.read_quarantine_records("openaq", "suspicious")
        for record in records:
            assert "warnings" in record
            assert "quarantine_reason" in record
            assert record["quarantine_reason"] == "SUSPICIOUS"


class TestQuarantineReading:
    """Test reading quarantine records."""

    def test_read_invalid_records(self, quarantine_manager, invalid_aq_records):
        """Test reading invalid records."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )

        records = quarantine_manager.read_quarantine_records("openaq", "invalid")
        assert len(records) >= 2

    def test_read_suspicious_records(self, quarantine_manager, suspicious_aq_records):
        """Test reading suspicious records."""
        quarantine_manager.quarantine_suspicious_records(
            "openaq", suspicious_aq_records, record_type="air_quality"
        )

        records = quarantine_manager.read_quarantine_records("openaq", "suspicious")
        assert len(records) == 1
        assert records[0]["value"] == 50.0

    def test_read_empty_quarantine(self, quarantine_manager):
        """Test reading from empty quarantine."""
        records = quarantine_manager.read_quarantine_records("openaq", "invalid")
        assert len(records) == 0


class TestQuarantineStats:
    """Test quarantine statistics."""

    def test_get_stats_invalid_records(self, quarantine_manager, invalid_aq_records):
        """Test statistics for invalid records."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )

        stats = quarantine_manager.get_quarantine_stats("openaq")
        assert stats["invalid"] >= 2
        assert stats["suspicious"] == 0
        assert stats["total"] >= 2

    def test_get_stats_suspicious_records(self, quarantine_manager, suspicious_aq_records):
        """Test statistics for suspicious records."""
        quarantine_manager.quarantine_suspicious_records(
            "openaq", suspicious_aq_records, record_type="air_quality"
        )

        stats = quarantine_manager.get_quarantine_stats("openaq")
        assert stats["invalid"] == 0
        assert stats["suspicious"] == 1
        assert stats["total"] == 1

    def test_get_stats_mixed_records(
        self, quarantine_manager, invalid_aq_records, suspicious_aq_records
    ):
        """Test statistics with both invalid and suspicious."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )
        quarantine_manager.quarantine_suspicious_records(
            "openaq", suspicious_aq_records, record_type="air_quality"
        )

        stats = quarantine_manager.get_quarantine_stats("openaq")
        assert stats["invalid"] >= 2
        assert stats["suspicious"] == 1
        assert stats["total"] >= 3


class TestPartitioningBySource:
    """Test that records are partitioned by source."""

    def test_different_sources_separated(self, quarantine_manager, invalid_aq_records):
        """Test different sources create separate directories."""
        # Quarantine same records from different sources
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )
        quarantine_manager.quarantine_invalid_records(
            "open_meteo", invalid_aq_records, record_type="air_quality"
        )

        # Check separate directories exist
        openaq_records = quarantine_manager.read_quarantine_records("openaq", "invalid")
        meteo_records = quarantine_manager.read_quarantine_records("open_meteo", "invalid")

        assert len(openaq_records) >= 2
        assert len(meteo_records) >= 2


class TestJSONLFormat:
    """Test JSONL format correctness."""

    def test_jsonl_format_valid(self, quarantine_manager, invalid_aq_records):
        """Test JSONL format is valid JSON."""
        quarantine_manager.quarantine_invalid_records(
            "openaq", invalid_aq_records, record_type="air_quality"
        )

        # Read raw file
        jsonl_files = list(
            (quarantine_manager.quarantine_root / "openaq").glob("**/*.jsonl")
        )
        assert len(jsonl_files) > 0

        # Verify JSON validity
        for jsonl_file in jsonl_files:
            with open(jsonl_file, "r") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        assert isinstance(record, dict)


class TestEdgeCases:
    """Test edge cases."""

    def test_quarantine_with_datetime_strings(self, quarantine_manager):
        """Test handling of datetime objects."""
        record = {
            "source": "openaq",
            "station_id": "123",
            "sensor_id": "456",
            "pollutant": "pm25",
            "value": -5.0,
            "unit": "µg/m³",
            "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
            "raw_payload_hash": "abc123",
        }

        quarantine_manager.quarantine_invalid_records(
            "openaq", [(record, ["Test reason"])], record_type="air_quality"
        )

        records = quarantine_manager.read_quarantine_records("openaq", "invalid")
        assert len(records) == 1
        # Datetime should be serialized to ISO string
        assert isinstance(records[0]["observed_at"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
