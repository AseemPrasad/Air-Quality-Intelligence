"""Regression tests for within-batch deduplication."""

from datetime import date, datetime, timezone

from aq_engine.quality.deduplication import Deduplicator


def _aq_record():
    return {
        "source": "openaq",
        "station_id": "123",
        "sensor_id": "456",
        "pollutant": "pm25",
        "value": 45.5,
        "unit": "ug/m3",
        "observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
        "ingested_at": datetime.now(timezone.utc),
        "raw_payload_hash": "hash-1",
    }


def _weather_record():
    return {
        "source": "open_meteo",
        "location_id": "123",
        "observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
        "temperature_c": 28.0,
        "humidity_pct": 60.0,
        "ingested_at": datetime.now(timezone.utc),
        "raw_payload_hash": "hash-2",
    }


def test_air_quality_duplicates_in_one_batch_are_removed(tmp_path):
    deduplicator = Deduplicator(storage_root=str(tmp_path))
    record = _aq_record()

    unique, duplicates = deduplicator.deduplicate_air_quality(
        [record, dict(record)], date(2026, 8, 15)
    )

    assert len(unique) == 1
    assert len(duplicates) == 1
    assert duplicates[0][0]["station_id"] == "123"


def test_weather_duplicates_in_one_batch_are_removed(tmp_path):
    deduplicator = Deduplicator(storage_root=str(tmp_path))
    record = _weather_record()

    unique, duplicates = deduplicator.deduplicate_weather(
        [record, dict(record)], date(2026, 8, 15)
    )

    assert len(unique) == 1
    assert len(duplicates) == 1
    assert duplicates[0][0]["location_id"] == "123"
