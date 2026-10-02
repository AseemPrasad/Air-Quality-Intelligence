"""Regression tests for the AnomalyDetector -> EventDetector hand-off.

AnomalyDetector.detect_anomalies()/detect_batch() emit ``hour_start`` as an ISO
8601 string (see the anomaly output contract in docs/03-anomaly-detection-logic.md),
but EventDetector previously assumed ``datetime`` objects. Feeding the first
stage's real output into the second therefore raised
``TypeError: Expected datetime, got str`` and no event could ever be produced.
These tests pin the contract between the two stages.
"""

from datetime import datetime, timedelta, timezone

import pytest

from aq_engine.analytics.anomaly import AnomalyDetector
from aq_engine.analytics.events import EventDetector

BASE = datetime(2026, 8, 15, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def detector():
    """EventDetector instance."""
    return EventDetector()


def _anomaly(hour_start, severity="HIGH", value=150.0, z=3.5):
    return {
        "location_id": "kolkata",
        "pollutant": "pm25",
        "hour_start": hour_start,
        "observed_value": value,
        "robust_z": z,
        "severity": severity,
    }


class TestAnomalyDetectorToEventDetectorPipeline:
    """Real AnomalyDetector output must be accepted by EventDetector."""

    def test_detect_batch_output_produces_an_event(self, detector):
        facts = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "hour_start": BASE + timedelta(hours=h),
                "observed_value": 300.0,
            }
            for h in range(3)
        ]
        baselines = {("kolkata", "pm25"): {"historical_median": 50.0, "mad": 10.0}}

        anomalies = AnomalyDetector().detect_batch(facts, baselines)
        assert isinstance(anomalies[0]["hour_start"], str)  # the contract

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["location_id"] == "kolkata"
        assert events[0]["anomaly_count"] == 3
        assert events[0]["duration_hours"] == 3
        assert events[0]["start_time"] == BASE.isoformat()


class TestHourStartFormats:
    """hour_start may be a datetime or any ISO 8601 string."""

    def test_z_suffix_strings(self, detector):
        anomalies = [
            _anomaly((BASE + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            for h in range(3)
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["start_time"] == BASE.isoformat()
        assert events[0]["end_time"] == (BASE + timedelta(hours=2)).isoformat()

    def test_naive_datetimes_are_treated_as_utc(self, detector):
        anomalies = [
            _anomaly((BASE + timedelta(hours=h)).replace(tzinfo=None)) for h in range(3)
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["start_time"] == BASE.isoformat()

    def test_mixed_datetime_and_string_inputs(self, detector):
        anomalies = [
            _anomaly(BASE),
            _anomaly((BASE + timedelta(hours=1)).isoformat()),
            _anomaly(BASE + timedelta(hours=2)),
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["anomaly_count"] == 3

    def test_non_utc_offsets_are_ordered_chronologically_not_lexically(self, detector):
        """06:30+05:30 is 01:00Z. Lexical ordering would put it last, not middle."""
        anomalies = [
            _anomaly("2026-08-15T00:00:00Z"),
            _anomaly("2026-08-15T06:30:00+05:30"),  # 01:00Z
            _anomaly("2026-08-15T02:00:00Z"),
        ]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["anomaly_count"] == 3
        assert events[0]["duration_hours"] == 3

    def test_unsorted_input_is_ordered_by_time(self, detector):
        hours = [2, 0, 1]
        anomalies = [_anomaly((BASE + timedelta(hours=h)).isoformat()) for h in hours]

        events = detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["start_time"] == BASE.isoformat()


class TestInvalidTimestamps:
    """A bad timestamp must not take down detection for everything else."""

    def test_missing_and_invalid_hour_start_are_skipped(self, detector):
        good = [_anomaly((BASE + timedelta(hours=h)).isoformat()) for h in range(3)]
        bad = [
            {k: v for k, v in _anomaly(None).items() if k != "hour_start"},
            _anomaly(None),
            _anomaly("not-a-timestamp"),
            _anomaly(""),
            _anomaly(12345),
        ]

        events = detector.detect_events(bad + good)

        assert len(events) == 1
        assert events[0]["anomaly_count"] == 3

    def test_only_invalid_timestamps_returns_no_events(self, detector):
        anomalies = [_anomaly("garbage") for _ in range(3)]

        assert detector.detect_events(anomalies) == []

    def test_input_dicts_are_not_mutated(self, detector):
        anomalies = [_anomaly((BASE + timedelta(hours=h)).isoformat()) for h in range(3)]
        snapshot = [dict(a) for a in anomalies]

        detector.detect_events(anomalies)

        assert anomalies == snapshot
        assert all(isinstance(a["hour_start"], str) for a in anomalies)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
