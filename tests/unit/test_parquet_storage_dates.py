"""Regression tests for observation-date partitioning in ParquetStorage."""

from datetime import datetime, timezone

from aq_engine.storage.parquet_io import ParquetStorage


def _air_record(station_id: str, observed_at: datetime):
    return {
        "source": "openaq",
        "station_id": station_id,
        "sensor_id": f"sensor-{station_id}",
        "pollutant": "pm25",
        "value": 40.0,
        "unit": "ug/m3",
        "observed_at": observed_at,
        "ingested_at": datetime.now(timezone.utc),
        "raw_payload_hash": f"hash-{station_id}",
    }


def test_batch_is_written_to_observation_dates_not_today(tmp_path):
    storage = ParquetStorage(str(tmp_path))
    records = [
        _air_record("1", datetime(2026, 8, 15, 12, tzinfo=timezone.utc)),
        _air_record("2", datetime(2026, 8, 16, 12, tzinfo=timezone.utc)),
    ]

    storage.write(records, source="openaq")

    assert (tmp_path / "openaq" / "year=2026" / "month=08" / "day=15").is_dir()
    assert (tmp_path / "openaq" / "year=2026" / "month=08" / "day=16").is_dir()


def test_read_range_finds_historical_backfill(tmp_path):
    storage = ParquetStorage(str(tmp_path))
    storage.write(
        [_air_record("1", datetime(2026, 8, 15, 12, tzinfo=timezone.utc))],
        source="openaq",
    )

    rows = storage.read_range("2026-08-15", "2026-08-15")

    assert len(rows) == 1
    assert rows[0]["station_id"] == "1"
