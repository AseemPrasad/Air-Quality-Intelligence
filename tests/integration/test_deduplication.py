"""Integration tests for deduplication and late-arrival handling.

Tests:
- Deduplication of duplicate records across ingestions
- Late-arrival classification and recomputation marking
- Out-of-lookback backfill handling
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, date, timezone
from unittest.mock import Mock, patch

from aq_engine.quality.deduplication import Deduplicator
from aq_engine.quality.late_arrival import LateLookbackProcessor, LateArrivalClassification


@pytest.fixture
def temp_storage():
    """Temporary storage directory."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aq_dedup_test_"))
    yield temp_dir
    if temp_dir.exists():
        import shutil
        shutil.rmtree(temp_dir)


@pytest.fixture
def deduplicator(temp_storage):
    """Deduplicator with temporary storage."""
    return Deduplicator(storage_root=str(temp_storage))


@pytest.fixture
def sample_aq_records():
    """Sample air quality records for testing."""
    base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "source": "openaq",
            "station_id": "123",
            "sensor_id": "456",
            "pollutant": "pm25",
            "value": 45.5,
            "unit": "µg/m³",
            "observed_at": base_time,
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "abc123",
        },
        {
            "source": "openaq",
            "station_id": "124",
            "sensor_id": "457",
            "pollutant": "pm25",
            "value": 52.3,
            "unit": "µg/m³",
            "observed_at": base_time + timedelta(minutes=30),
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "abc124",
        },
        {
            "source": "openaq",
            "station_id": "125",
            "sensor_id": "458",
            "pollutant": "pm10",
            "value": 120.0,
            "unit": "µg/m³",
            "observed_at": base_time + timedelta(hours=1),
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "abc125",
        },
    ]


@pytest.fixture
def sample_weather_records():
    """Sample weather records for testing."""
    base_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "source": "open_meteo",
            "location_id": "kolkata",
            "observed_at": base_time,
            "temperature_c": 28.5,
            "humidity_pct": 65.0,
            "wind_speed_kmh": 8.5,
            "wind_direction_deg": 180.0,
            "pressure_hpa": 1013.0,
            "precipitation_mm": 0.1,
            "cloud_cover_pct": 40.0,
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "wx123",
        },
        {
            "source": "open_meteo",
            "location_id": "kolkata",
            "observed_at": base_time + timedelta(hours=1),
            "temperature_c": 29.2,
            "humidity_pct": 62.0,
            "wind_speed_kmh": 9.0,
            "wind_direction_deg": 190.0,
            "pressure_hpa": 1012.5,
            "precipitation_mm": 0.0,
            "cloud_cover_pct": 35.0,
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "wx124",
        },
    ]


class TestDeduplication:
    """Test deduplication logic."""

    def test_no_duplicates_on_first_write(self, deduplicator, sample_aq_records):
        """Test first write: all records are unique (no partition exists)."""
        unique, dups = deduplicator.deduplicate_air_quality(
            sample_aq_records, date(2026, 8, 15)
        )

        assert len(unique) == 3
        assert len(dups) == 0

    def test_empty_input_returns_empty(self, deduplicator):
        """Test empty input."""
        unique, dups = deduplicator.deduplicate_air_quality([], date(2026, 8, 15))

        assert len(unique) == 0
        assert len(dups) == 0

    def test_weather_deduplication_first_write(self, deduplicator, sample_weather_records):
        """Test weather deduplication on first write."""
        unique, dups = deduplicator.deduplicate_weather(
            sample_weather_records, date(2026, 8, 15)
        )

        assert len(unique) == 2
        assert len(dups) == 0

    def test_deduplication_stats(self, deduplicator, sample_aq_records):
        """Test deduplication statistics calculation."""
        unique, dups = deduplicator.deduplicate_air_quality(
            sample_aq_records, date(2026, 8, 15)
        )

        stats = deduplicator.get_deduplication_stats(sample_aq_records, unique, dups)

        assert stats["total_input"] == 3
        assert stats["unique"] == 3
        assert stats["duplicates"] == 0
        assert stats["dedup_ratio"] == 0.0

    def test_mixed_unique_and_duplicates(self, deduplicator, sample_aq_records):
        """Test mix of unique and duplicate records."""
        from aq_engine.quality.hashing import generate_measurement_key

        # Create batch with 2 duplicates of first record
        new_batch = [
            sample_aq_records[0],  # Duplicate
            sample_aq_records[1],  # Unique
            sample_aq_records[0],  # Duplicate
        ]

        # Mock existing keys to include the first record
        key_0 = generate_measurement_key(
            source=sample_aq_records[0].get("source"),
            station_id=sample_aq_records[0].get("station_id"),
            sensor_id=sample_aq_records[0].get("sensor_id"),
            pollutant=sample_aq_records[0].get("pollutant"),
            observed_at=sample_aq_records[0].get("observed_at"),
        )

        with patch.object(deduplicator, "_get_existing_aq_keys", return_value={key_0}):
            unique, dups = deduplicator.deduplicate_air_quality(new_batch, date(2026, 8, 15))

            # Should find 2 duplicates (both of first record) and 1 unique (second record)
            assert len(unique) == 1
            assert len(dups) == 2


class TestLateLookback:
    """Test late-arrival classification and recomputation marking."""

    @pytest.fixture
    def processor(self):
        """LateLookbackProcessor with 6-hour lookback."""
        return LateLookbackProcessor(lookback_hours=6.0)

    def test_immediate_classification(self, processor):
        """Test records <1 hour old classified as IMMEDIATE."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        recent_time = current_time - timedelta(minutes=30)

        records = [
            {"observed_at": recent_time, "value": 45.5},
        ]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["immediate_count"] == 1
        assert result["recent_count"] == 0
        assert result["backfill_count"] == 0
        assert result["recomputation_marked"] is True

    def test_recent_classification(self, processor):
        """Test records 1-6 hours old classified as RECENT."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        old_time = current_time - timedelta(hours=3)

        records = [
            {"observed_at": old_time, "value": 45.5},
        ]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["immediate_count"] == 0
        assert result["recent_count"] == 1
        assert result["backfill_count"] == 0
        assert result["recomputation_marked"] is True

    def test_backfill_classification(self, processor):
        """Test records >6 hours old classified as BACKFILL."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        old_time = current_time - timedelta(hours=12)

        records = [
            {"observed_at": old_time, "value": 45.5},
        ]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["immediate_count"] == 0
        assert result["recent_count"] == 0
        assert result["backfill_count"] == 1
        assert result["recomputation_marked"] is False

    def test_affected_hourly_partitions(self, processor):
        """Test affected hourly partitions marked correctly."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

        records = [
            {"observed_at": datetime(2026, 8, 15, 8, 30, 0, tzinfo=timezone.utc)},
            {"observed_at": datetime(2026, 8, 15, 9, 45, 0, tzinfo=timezone.utc)},
        ]

        result = processor.classify_and_mark(records, current_time=current_time)

        # Should mark hourly partitions for 8:00-9:00 and 9:00-10:00
        assert len(result["affected_hourly_partitions"]) == 2
        assert (date(2026, 8, 15), 8) in result["affected_hourly_partitions"]
        assert (date(2026, 8, 15), 9) in result["affected_hourly_partitions"]

    def test_no_recomputation_for_backfill(self, processor):
        """Test backfill records don't mark partitions for recomputation."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        old_time = current_time - timedelta(hours=12)

        records = [
            {"observed_at": old_time},
        ]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["recomputation_marked"] is False
        assert len(result["affected_hourly_partitions"]) == 0

    def test_needs_recomputation(self, processor):
        """Test needs_recomputation check."""
        current_time = datetime.now(timezone.utc)
        recent = current_time - timedelta(hours=2)
        old = current_time - timedelta(hours=12)

        assert processor.needs_recomputation({"observed_at": recent}) is True
        assert processor.needs_recomputation({"observed_at": old}) is False

    def test_split_records_by_lookback(self, processor):
        """Test splitting records by lookback window."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

        records = [
            {"observed_at": current_time - timedelta(hours=2)},  # Lookback
            {"observed_at": current_time - timedelta(hours=12)},  # Backfill
            {"observed_at": current_time - timedelta(hours=1)},  # Lookback
        ]

        # Create a processor and manually test the split logic
        lookback_records = []
        backfill_records = []

        for record in records:
            observed_at = record.get("observed_at")
            age = current_time - observed_at
            if age <= processor.lookback_window:
                lookback_records.append(record)
            else:
                backfill_records.append(record)

        assert len(lookback_records) == 2
        assert len(backfill_records) == 1

    def test_get_affected_hourly_partition(self, processor):
        """Test getting affected hourly partition from record."""
        record = {"observed_at": datetime(2026, 8, 15, 8, 30, 45, tzinfo=timezone.utc)}

        partition = processor.get_affected_hourly_partition(record)

        assert partition == (date(2026, 8, 15), 8)

    def test_lookback_window_range(self, processor):
        """Test getting lookback window range."""
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

        start, end = processor.get_lookback_window_range(current_time=current_time)

        assert end == current_time
        assert (end - start).total_seconds() == 6 * 3600  # 6 hours


class TestLateArrivalIntegration:
    """Integration tests for late-arrival scenarios."""

    def test_real_time_observation(self):
        """Test observation arriving within 1 hour."""
        processor = LateLookbackProcessor(lookback_hours=6)
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        record_time = current_time - timedelta(minutes=30)

        records = [{"observed_at": record_time, "value": 45.5}]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["immediate_count"] == 1
        assert result["recomputation_marked"] is True
        assert len(result["affected_hourly_partitions"]) == 1

    def test_late_arrival_within_lookback(self):
        """Test observation arriving 3 hours after occurrence."""
        processor = LateLookbackProcessor(lookback_hours=6)
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        observation_time = datetime(2026, 8, 15, 8, 30, 0, tzinfo=timezone.utc)

        records = [{"observed_at": observation_time, "value": 45.5}]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["recent_count"] == 1
        assert result["recomputation_marked"] is True
        # Should mark 08:00 hourly partition
        assert (date(2026, 8, 15), 8) in result["affected_hourly_partitions"]

    def test_backfill_beyond_lookback(self):
        """Test observation beyond 6-hour lookback (backfill)."""
        processor = LateLookbackProcessor(lookback_hours=6)
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        observation_time = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)  # 24 hours old

        records = [{"observed_at": observation_time, "value": 45.5}]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["backfill_count"] == 1
        assert result["recomputation_marked"] is False
        assert len(result["affected_hourly_partitions"]) == 0

    def test_mixed_arrival_times(self):
        """Test batch with mixed arrival times."""
        processor = LateLookbackProcessor(lookback_hours=6)
        current_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

        records = [
            {"observed_at": current_time - timedelta(minutes=30)},  # Immediate
            {"observed_at": current_time - timedelta(hours=3)},  # Recent
            {"observed_at": current_time - timedelta(hours=12)},  # Backfill
        ]

        result = processor.classify_and_mark(records, current_time=current_time)

        assert result["immediate_count"] == 1
        assert result["recent_count"] == 1
        assert result["backfill_count"] == 1
        assert result["recomputation_marked"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def _write_aq_parquet(partition_path: Path, records: list) -> None:
    """Write AQ records directly as a Parquet file using Polars.

    Bypasses ParquetWriter so tests are independent of the date_partition_path
    bug fixed in PR #1.  Writes only the columns that _get_existing_aq_keys
    needs to recompute measurement keys.
    """
    import polars as pl

    partition_path.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "source": r["source"],
            "station_id": r["station_id"],
            "sensor_id": r["sensor_id"],
            "pollutant": r["pollutant"],
            "observed_at": r["observed_at"],
        }
        for r in records
    ]
    df = pl.DataFrame(rows)
    df.write_parquet(str(partition_path / "data.parquet"))


def _write_weather_parquet(partition_path: Path, records: list) -> None:
    """Write weather records directly as a Parquet file using Polars.

    Bypasses ParquetWriter so tests are independent of the date_partition_path
    bug fixed in PR #1.  Writes only the columns that _get_existing_weather_keys
    needs to recompute weather keys.
    """
    import polars as pl

    partition_path.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "source": r["source"],
            "location_id": r["location_id"],
            "observed_at": r["observed_at"],
        }
        for r in records
    ]
    df = pl.DataFrame(rows)
    df.write_parquet(str(partition_path / "data.parquet"))


class TestExistingKeyLoading:
    """Regression tests for _get_existing_aq_keys / _get_existing_weather_keys.

    Prior to the fix, both methods discovered Parquet files in the partition
    directory but always returned an empty set instead of reading them.
    This meant that re-ingesting the same records was never detected as a
    duplicate — every record appeared new.

    These tests write Parquet files directly with Polars (bypassing
    ParquetWriter) so they remain independent of the date_partition_path
    bug addressed in PR #1.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _aq_partition_path(self, storage_root: Path, d: date) -> Path:
        return (
            storage_root
            / "openaq"
            / f"year={d.year}"
            / f"month={d.month:02d}"
            / f"day={d.day:02d}"
        )

    def _weather_partition_path(self, storage_root: Path, d: date) -> Path:
        return (
            storage_root
            / "weather"
            / f"year={d.year}"
            / f"month={d.month:02d}"
            / f"day={d.day:02d}"
        )

    # ------------------------------------------------------------------
    # Air-quality key loading
    # ------------------------------------------------------------------

    def test_existing_aq_keys_loaded_from_parquet(
        self, deduplicator, temp_storage, sample_aq_records
    ):
        """Keys written in a previous run are loaded from the Parquet partition."""
        partition_date = date(2026, 8, 15)
        partition_path = self._aq_partition_path(temp_storage, partition_date)
        _write_aq_parquet(partition_path, sample_aq_records)

        # Must return a non-empty set now that files exist on disk
        keys = deduplicator._get_existing_aq_keys(partition_date)

        assert len(keys) == len(sample_aq_records)
        assert all(isinstance(k, str) and len(k) == 64 for k in keys)

    def test_existing_aq_key_matches_incoming_key(
        self, deduplicator, temp_storage, sample_aq_records
    ):
        """Key recomputed from Parquet matches key computed from the original record."""
        from aq_engine.quality.hashing import generate_measurement_key

        partition_date = date(2026, 8, 15)
        partition_path = self._aq_partition_path(temp_storage, partition_date)
        _write_aq_parquet(partition_path, sample_aq_records)

        existing_keys = deduplicator._get_existing_aq_keys(partition_date)

        for record in sample_aq_records:
            expected_key = generate_measurement_key(
                source=record["source"],
                station_id=record["station_id"],
                sensor_id=record["sensor_id"],
                pollutant=record["pollutant"],
                observed_at=record["observed_at"],
            )
            assert expected_key in existing_keys

    def test_duplicate_aq_records_detected_after_first_write(
        self, deduplicator, temp_storage, sample_aq_records
    ):
        """Re-submitting already-written records is detected as duplicates."""
        partition_date = date(2026, 8, 15)
        partition_path = self._aq_partition_path(temp_storage, partition_date)
        _write_aq_parquet(partition_path, sample_aq_records)

        # Second ingestion of the same records — all must be flagged as dups
        unique, dups = deduplicator.deduplicate_air_quality(
            sample_aq_records, partition_date
        )

        assert len(dups) == len(sample_aq_records)
        assert len(unique) == 0

    def test_new_aq_records_not_rejected_when_partition_exists(
        self, deduplicator, temp_storage, sample_aq_records
    ):
        """A genuinely new record is not incorrectly flagged as a duplicate."""
        partition_date = date(2026, 8, 15)
        partition_path = self._aq_partition_path(temp_storage, partition_date)
        _write_aq_parquet(partition_path, sample_aq_records)

        # Build a new record with a different station/timestamp — must be unique
        new_record = {
            "source": "openaq",
            "station_id": "999",
            "sensor_id": "999",
            "pollutant": "pm25",
            "value": 33.0,
            "unit": "µg/m³",
            "observed_at": datetime(2026, 8, 15, 23, 0, 0, tzinfo=timezone.utc),
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "newrecord",
        }

        unique, dups = deduplicator.deduplicate_air_quality(
            [new_record], partition_date
        )

        assert len(unique) == 1
        assert len(dups) == 0

    # ------------------------------------------------------------------
    # Weather key loading
    # ------------------------------------------------------------------

    def test_existing_weather_keys_loaded_from_parquet(
        self, deduplicator, temp_storage, sample_weather_records
    ):
        """Weather keys written in a previous run are loaded from the partition."""
        partition_date = date(2026, 8, 15)
        partition_path = self._weather_partition_path(temp_storage, partition_date)
        _write_weather_parquet(partition_path, sample_weather_records)

        keys = deduplicator._get_existing_weather_keys(partition_date)

        assert len(keys) == len(sample_weather_records)
        assert all(isinstance(k, str) and len(k) == 64 for k in keys)

    def test_duplicate_weather_records_detected_after_first_write(
        self, deduplicator, temp_storage, sample_weather_records
    ):
        """Re-submitting already-written weather records is detected as duplicates."""
        partition_date = date(2026, 8, 15)
        partition_path = self._weather_partition_path(temp_storage, partition_date)
        _write_weather_parquet(partition_path, sample_weather_records)

        unique, dups = deduplicator.deduplicate_weather(
            sample_weather_records, partition_date
        )

        assert len(dups) == len(sample_weather_records)
        assert len(unique) == 0

    # ------------------------------------------------------------------
    # Edge cases — empty / missing partitions (pre-existing behaviour)
    # ------------------------------------------------------------------

    def test_no_partition_dir_returns_empty_set(self, deduplicator):
        """Missing partition directory returns empty set without error."""
        keys = deduplicator._get_existing_aq_keys(date(2020, 1, 1))
        assert keys == set()

    def test_empty_partition_dir_returns_empty_set(self, deduplicator, temp_storage):
        """Existing but empty partition directory returns empty set."""
        empty_dir = (
            temp_storage / "openaq" / "year=2026" / "month=01" / "day=01"
        )
        empty_dir.mkdir(parents=True)

        keys = deduplicator._get_existing_aq_keys(date(2026, 1, 1))
        assert keys == set()

    def test_no_weather_partition_returns_empty_set(self, deduplicator):
        """Missing weather partition directory returns empty set without error."""
        keys = deduplicator._get_existing_weather_keys(date(2020, 1, 1))
        assert keys == set()
