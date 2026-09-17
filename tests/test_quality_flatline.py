from datetime import datetime, timedelta, timezone

from aq_engine.quality.flatline import FlatlineValidator
from aq_engine.quality.drift import SensorDriftValidator


def make_record(station_id: str, pollutant: str, value: float, observed_at: datetime) -> dict:
    return {
        "source": "openaq",
        "station_id": station_id,
        "sensor_id": f"sensor-{station_id}",
        "pollutant": pollutant,
        "value": value,
        "unit": "µg/m³",
        "observed_at": observed_at,
        "ingested_at": observed_at + timedelta(minutes=5),
        "raw_payload_hash": f"hash-{station_id}-{observed_at.isoformat()}",
    }


def test_flatline_validator_flags_six_hour_constant_signal():
    start = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)
    records = [
        make_record("stn_flat", "pm25", 42.0, start + timedelta(hours=i))
        for i in range(6)
    ]

    validator = FlatlineValidator(min_hours=6)
    flagged = validator.flag_records(records)

    assert flagged
    assert all(record.get("quality_flag") == "STUCK_SENSOR" for record in flagged)


def test_sensor_drift_validator_flags_station_deviation_from_neighbors():
    start = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    stable_records = [
        make_record("stn_base", "pm25", 42.0, start + timedelta(hours=i))
        for i in range(168)
    ]
    drift_records = [
        make_record("stn_drift", "pm25", 42.0 + (i * 0.25), start + timedelta(hours=i))
        for i in range(168)
    ]

    validator = SensorDriftValidator(min_points=48, slope_threshold=0.05, neighbor_deviation=0.2)
    flagged = validator.flag_records(stable_records + drift_records)

    assert flagged
    assert any(record.get("station_id") == "stn_drift" for record in flagged)
    assert any(record.get("quality_flag") == "DRIFT_DETECTED" for record in flagged)
