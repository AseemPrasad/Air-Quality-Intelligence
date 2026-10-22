"""Regression tests for date partitioning in quarantine storage."""

from datetime import datetime, timezone

from aq_engine.quality.quarantine import QuarantineManager


def _invalid_record(station_id: str, observed_at: datetime):
    return (
        {
            "source": "openaq",
            "station_id": station_id,
            "sensor_id": "sensor-1",
            "pollutant": "pm25",
            "value": -1.0,
            "unit": "ug/m3",
            "observed_at": observed_at,
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "hash",
        },
        ["value must be non-negative"],
    )


def test_invalid_records_are_written_to_their_observation_dates(tmp_path):
    manager = QuarantineManager(str(tmp_path))
    records = [
        _invalid_record("station-1", datetime(2026, 8, 15, 12, tzinfo=timezone.utc)),
        _invalid_record("station-2", datetime(2026, 8, 16, 12, tzinfo=timezone.utc)),
    ]

    manager.quarantine_invalid_records("openaq", records)

    first = tmp_path / "openaq" / "year=2026" / "month=08" / "day=15"
    second = tmp_path / "openaq" / "year=2026" / "month=08" / "day=16"
    assert len(list(first.glob("*.jsonl"))) == 1
    assert len(list(second.glob("*.jsonl"))) == 1


def test_suspicious_batch_spanning_dates_creates_both_partitions(tmp_path):
    manager = QuarantineManager(str(tmp_path))
    records = [
        _invalid_record("station-1", datetime(2026, 8, 15, 1, tzinfo=timezone.utc)),
        _invalid_record("station-2", datetime(2026, 8, 17, 1, tzinfo=timezone.utc)),
    ]

    manager.quarantine_suspicious_records("openaq", records)

    first = tmp_path / "openaq" / "suspicious" / "year=2026" / "month=08" / "day=15"
    second = tmp_path / "openaq" / "suspicious" / "year=2026" / "month=08" / "day=17"
    assert len(list(first.glob("*.jsonl"))) == 1
    assert len(list(second.glob("*.jsonl"))) == 1
