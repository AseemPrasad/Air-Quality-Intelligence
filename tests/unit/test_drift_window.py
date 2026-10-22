"""Regression tests for drift window selection and timestamp handling."""

from datetime import datetime, timedelta, timezone

from aq_engine.quality.drift import SensorDriftValidator


def _series(station_id, values, base, *, missing_index=None):
    records = []
    for index, value in enumerate(values):
        observed_at = base + timedelta(hours=index)
        if index == missing_index:
            observed_at = None
        records.append(
            {
                "station_id": station_id,
                "pollutant": "pm25",
                "value": float(value),
                "observed_at": observed_at,
            }
        )
    return records


def test_drift_outside_window_is_ignored():
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    values = [10.0] * 90 + [10, 100, 200, 300, 400, 10, 10, 10, 10, 10]
    drift = _series("st1", values, base)
    stable = _series("st2", [10.0] * 100, base)

    validator = SensorDriftValidator(
        min_points=10,
        slope_threshold=0.05,
        neighbor_deviation=0.2,
        window_hours=5,
    )

    assert validator.flag_records(drift + stable) == []


def test_mixed_naive_and_aware_timestamps_do_not_raise():
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    drift = _series("st1", [10.0] * 20, base, missing_index=3)
    drift[5]["observed_at"] = drift[5]["observed_at"].replace(tzinfo=None)
    stable = _series("st2", [10.0] * 20, base)

    validator = SensorDriftValidator(min_points=5, window_hours=168)

    assert validator.flag_records(drift + stable) == []
