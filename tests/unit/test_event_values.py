"""Event statistics must handle zero and missing observed values."""

from datetime import datetime, timedelta, timezone

import pytest

from aq_engine.analytics.events import EventDetector

BASE = datetime(2026, 8, 15, 8, 0, 0, tzinfo=timezone.utc)


def _anomaly(hour, value, severity="HIGH", z=3.0):
    return {
        "location_id": "kolkata",
        "pollutant": "pm25",
        "hour_start": BASE + timedelta(hours=hour),
        "observed_value": value,
        "robust_z": z,
        "severity": severity,
    }


def test_zero_readings_count_toward_the_event_mean():
    events = EventDetector().detect_events(
        [_anomaly(0, 0.0), _anomaly(1, 0.0), _anomaly(2, 30.0)]
    )

    assert len(events) == 1
    assert events[0]["mean_value"] == pytest.approx(10.0)
    assert events[0]["peak_value"] == 30.0


def test_merging_an_event_without_values_keeps_the_other_events_stats():
    detector = EventDetector()
    with_values = detector._create_event(
        "kolkata", "pm25", [_anomaly(0, 90.0), _anomaly(1, 110.0), _anomaly(2, 100.0)]
    )
    without_values = detector._create_event(
        "kolkata", "pm25", [_anomaly(3, None), _anomaly(4, None), _anomaly(5, None)]
    )

    merged = detector._merge_two_events(with_values, without_values)

    assert merged["peak_value"] == 110.0
    assert merged["mean_value"] == pytest.approx(100.0)
    assert merged["anomaly_count"] == 6


def test_merging_two_events_without_values_leaves_stats_empty():
    detector = EventDetector()
    first = detector._create_event(
        "kolkata", "pm25", [_anomaly(h, None) for h in (0, 1, 2)]
    )
    second = detector._create_event(
        "kolkata", "pm25", [_anomaly(h, None) for h in (3, 4, 5)]
    )

    merged = detector._merge_two_events(first, second)

    assert merged["peak_value"] is None
    assert merged["mean_value"] is None
