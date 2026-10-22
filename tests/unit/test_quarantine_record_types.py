"""Regression tests for quarantine record-type isolation."""

from datetime import datetime, timezone

from aq_engine.quality.quarantine import QuarantineManager


def _record(station_id: str):
    return (
        {
            "source": "openaq",
            "station_id": station_id,
            "sensor_id": "sensor-1",
            "pollutant": "pm25",
            "value": 42.0,
            "unit": "ug/m3",
            "observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": "hash",
        },
        ["reason"],
    )


def test_invalid_reader_excludes_suspicious_records(tmp_path):
    manager = QuarantineManager(str(tmp_path))
    manager.quarantine_suspicious_records("openaq", [_record("station-1")])

    assert manager.read_quarantine_records("openaq", "invalid") == []


def test_invalid_and_suspicious_readers_return_only_their_own_records(tmp_path):
    manager = QuarantineManager(str(tmp_path))
    manager.quarantine_invalid_records("openaq", [_record("invalid-1")])
    manager.quarantine_suspicious_records("openaq", [_record("suspicious-1")])

    invalid = manager.read_quarantine_records("openaq", "invalid")
    suspicious = manager.read_quarantine_records("openaq", "suspicious")

    assert [record["station_id"] for record in invalid] == ["invalid-1"]
    assert [record["station_id"] for record in suspicious] == ["suspicious-1"]
