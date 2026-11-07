
"""Comprehensive unit tests for analytics modules.

Covers anomaly detection, pollution event detection and merging,
and station health scoring using the actual production classes.
"""

from datetime import datetime, timedelta, timezone, date

import pytest

from aq_engine.analytics.anomaly import (
    AnomalyDetector,
    AnomalySeverity,
)
from aq_engine.analytics.events import EventDetector
from aq_engine.analytics.station_health import (
    StationHealthScorer,
    HealthStatus,
)


@pytest.fixture
def anomaly_detector():
    return AnomalyDetector()


@pytest.fixture
def event_detector():
    return EventDetector()


@pytest.fixture
def health_scorer():
    return StationHealthScorer()


@pytest.fixture
def baseline():
    return {
        "historical_median": 50.0,
        "mad": 10.0,
    }


@pytest.fixture
def hourly_fact():
    return {
        "location_id": "kolkata",
        "pollutant": "pm25",
        "observed_value": 50.0,
        "hour_start": datetime(
            2026, 8, 15, 10, 0, tzinfo=timezone.utc
        ),
    }


def make_anomaly(hour, severity="HIGH", value=100.0, robust_z=3.0):
    """Create an anomaly record for event detector tests."""
    return {
        "location_id": "kolkata",
        "pollutant": "pm25",
        "hour_start": datetime(
            2026, 8, 15, hour, 0, tzinfo=timezone.utc
        ).isoformat(),
        "observed_value": value,
        "robust_z": robust_z,
        "severity": severity,
    }


class TestAnomalyDetection:
    """Test production anomaly detection."""

    def test_normal_value(self, anomaly_detector, hourly_fact, baseline):
        result = anomaly_detector.detect_anomalies(
            hourly_fact, baseline
        )

        assert result["severity"] == AnomalySeverity.NORMAL.value
        assert result["robust_z"] == 0.0
        assert result["fallback_used"] is False

    def test_elevated_anomaly(self, anomaly_detector, hourly_fact, baseline):
        hourly_fact["observed_value"] = 50.0 + (
            2.5 * anomaly_detector.MAD_CONSTANT * 10.0
        )

        result = anomaly_detector.detect_anomalies(
            hourly_fact, baseline
        )

        assert result["severity"] == AnomalySeverity.ELEVATED.value
        assert result["robust_z"] == pytest.approx(2.5)

    def test_high_anomaly(self, anomaly_detector, hourly_fact, baseline):
        hourly_fact["observed_value"] = 50.0 + (
            3.5 * anomaly_detector.MAD_CONSTANT * 10.0
        )

        result = anomaly_detector.detect_anomalies(
            hourly_fact, baseline
        )

        assert result["severity"] == AnomalySeverity.HIGH.value
        assert result["robust_z"] == pytest.approx(3.5)

    def test_severe_anomaly(self, anomaly_detector, hourly_fact, baseline):
        hourly_fact["observed_value"] = 50.0 + (
            4.5 * anomaly_detector.MAD_CONSTANT * 10.0
        )

        result = anomaly_detector.detect_anomalies(
            hourly_fact, baseline
        )

        assert result["severity"] == AnomalySeverity.SEVERE.value

    def test_extreme_anomaly(self, anomaly_detector, hourly_fact, baseline):
        hourly_fact["observed_value"] = 50.0 + (
            5.5 * anomaly_detector.MAD_CONSTANT * 10.0
        )

        result = anomaly_detector.detect_anomalies(
            hourly_fact, baseline
        )

        assert result["severity"] == AnomalySeverity.EXTREME.value

    def test_negative_anomaly_uses_absolute_z_score(
        self, anomaly_detector, hourly_fact, baseline
    ):
        hourly_fact["observed_value"] = 50.0 - (
            3.5 * anomaly_detector.MAD_CONSTANT * 10.0
        )

        result = anomaly_detector.detect_anomalies(
            hourly_fact, baseline
        )

        assert result["severity"] == AnomalySeverity.HIGH.value
        assert result["robust_z"] < 0

    def test_zero_mad_constant_history(
        self, anomaly_detector, hourly_fact
    ):
        constant_baseline = {
            "historical_median": 50.0,
            "mad": 0.0,
        }

        result = anomaly_detector.detect_anomalies(
            hourly_fact, constant_baseline
        )

        assert result["severity"] == AnomalySeverity.NORMAL.value
        assert result["robust_z"] == 0.0

    def test_zero_mad_detects_deviation(
        self, anomaly_detector, hourly_fact
    ):
        hourly_fact["observed_value"] = 80.0

        constant_baseline = {
            "historical_median": 50.0,
            "mad": 0.0,
        }

        result = anomaly_detector.detect_anomalies(
            hourly_fact, constant_baseline
        )

        assert result["severity"] == AnomalySeverity.HIGH.value
        assert result["robust_z"] == 3.0

    def test_missing_baseline_uses_citywide_fallback(
        self, anomaly_detector, hourly_fact
    ):
        fallback = {
            ("citywide", "pm25"): {
                "historical_median": 50.0,
                "mad": 10.0,
            }
        }

        result = anomaly_detector.detect_anomalies(
            hourly_fact,
            baseline=None,
            fallback_baselines=fallback,
        )

        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "citywide_fallback"
        assert result["baseline_median"] == 50.0

    def test_missing_baseline_uses_recent_fallback(
        self, anomaly_detector, hourly_fact
    ):
        fallback = {
            ("recent_7d", "pm25"): {
                "historical_median": 40.0,
                "mad": 5.0,
            }
        }

        result = anomaly_detector.detect_anomalies(
            hourly_fact,
            baseline=None,
            fallback_baselines=fallback,
        )

        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "recent_7day_fallback"
        assert result["baseline_median"] == 40.0

    def test_no_baseline_returns_safe_result(
        self, anomaly_detector, hourly_fact
    ):
        result = anomaly_detector.detect_anomalies(
            hourly_fact,
            baseline=None,
            fallback_baselines=None,
        )

        assert result["severity"] == AnomalySeverity.NORMAL.value
        assert result["robust_z"] is None
        assert result["baseline_median"] is None
        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "no_baseline_available"

    def test_batch_detection(
        self, anomaly_detector, hourly_fact, baseline
    ):
        facts = [hourly_fact.copy(), hourly_fact.copy()]
        facts[1]["observed_value"] = 100.0

        baselines = {
            ("kolkata", "pm25"): baseline,
        }

        results = anomaly_detector.detect_batch(
            facts,
            baselines,
        )

        assert len(results) == 2
        assert results[0]["severity"] == "NORMAL"
        assert results[1]["severity"] == "HIGH"

    def test_anomaly_summary(self, anomaly_detector):
        results = [
            {"severity": "NORMAL"},
            {"severity": "HIGH"},
            {"severity": "EXTREME"},
            {"severity": "ELEVATED"},
        ]

        summary = anomaly_detector.get_anomaly_summary(results)

        assert summary["total_checked"] == 4
        assert summary["total_anomalies"] == 3
        assert summary["normal"] == 1
        assert summary["high"] == 1
        assert summary["extreme"] == 1
        assert summary["elevated"] == 1
        assert summary["anomaly_rate"] == pytest.approx(0.75)

    def test_empty_anomaly_summary(self, anomaly_detector):
        summary = anomaly_detector.get_anomaly_summary([])

        assert summary["total_checked"] == 0
        assert summary["total_anomalies"] == 0
        assert summary["normal"] == 0


class TestEventDetection:
    """Test production pollution event detection."""

    def test_three_consecutive_high_anomalies(self, event_detector):
        anomalies = [
            make_anomaly(10),
            make_anomaly(11),
            make_anomaly(12),
        ]

        events = event_detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["location_id"] == "kolkata"
        assert events[0]["pollutant"] == "pm25"
        assert events[0]["anomaly_count"] == 3
        assert events[0]["severity"] == "HIGH"

    def test_two_high_anomalies_do_not_trigger_event(
        self, event_detector
    ):
        anomalies = [
            make_anomaly(10),
            make_anomaly(11),
        ]

        events = event_detector.detect_events(anomalies)

        assert events == []

    def test_normal_anomalies_do_not_trigger_event(
        self, event_detector
    ):
        anomalies = [
            make_anomaly(10, severity="NORMAL"),
            make_anomaly(11, severity="NORMAL"),
            make_anomaly(12, severity="NORMAL"),
        ]

        events = event_detector.detect_events(anomalies)

        assert events == []

    def test_three_anomalies_within_four_hour_window(
        self, event_detector
    ):
        anomalies = [
            make_anomaly(9),
            make_anomaly(10),
            make_anomaly(12),
        ]

        events = event_detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["anomaly_count"] == 3

    def test_anomalies_outside_four_hour_window(
        self, event_detector
    ):
        anomalies = [
            make_anomaly(9),
            make_anomaly(10),
            make_anomaly(14),
        ]

        events = event_detector.detect_events(anomalies)

        assert events == []

    def test_iso_timestamp_support(self, event_detector):
        anomalies = [
            make_anomaly(10),
            make_anomaly(11),
            make_anomaly(12),
        ]

        events = event_detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["start_time"].startswith("2026-08-15T10:00")

    def test_unordered_anomalies_are_sorted(self, event_detector):
        anomalies = [
            make_anomaly(12),
            make_anomaly(10),
            make_anomaly(11),
        ]

        events = event_detector.detect_events(anomalies)

        assert len(events) == 1
        assert events[0]["anomaly_count"] == 3

    def test_invalid_timestamp_is_skipped(self, event_detector):
        anomalies = [
            make_anomaly(10),
            make_anomaly(11),
            {
                **make_anomaly(12),
                "hour_start": "invalid-timestamp",
            },
        ]

        events = event_detector.detect_events(anomalies)

        assert events == []

    def test_different_locations_are_not_combined(
        self, event_detector
    ):
        anomalies = [
            make_anomaly(10),
            make_anomaly(11),
            make_anomaly(12),
            {
                **make_anomaly(10),
                "location_id": "delhi",
            },
            {
                **make_anomaly(11),
                "location_id": "delhi",
            },
            {
                **make_anomaly(12),
                "location_id": "delhi",
            },
        ]

        events = event_detector.detect_events(anomalies)

        assert len(events) == 2
        assert {event["location_id"] for event in events} == {
            "kolkata",
            "delhi",
        }

    def test_event_statistics(self, event_detector):
        anomalies = [
            make_anomaly(10, value=50.0, robust_z=3.0),
            make_anomaly(11, value=70.0, robust_z=4.0),
            make_anomaly(12, value=90.0, robust_z=5.0),
        ]

        events = event_detector.detect_events(anomalies)

        assert len(events) == 1

        event = events[0]

        assert event["peak_value"] == 90.0
        assert event["mean_value"] == pytest.approx(70.0)
        assert event["peak_anomaly_score"] == 5.0
        assert event["duration_hours"] == 3
        assert event["anomaly_count"] == 3

    def test_empty_event_input(self, event_detector):
        assert event_detector.detect_events([]) == []

    def test_event_id_is_deterministic(self, event_detector):
        start = datetime(
            2026, 8, 15, 10, 0, tzinfo=timezone.utc
        )

        first = event_detector._generate_event_id(
            "kolkata", "pm25", start
        )
        second = event_detector._generate_event_id(
            "kolkata", "pm25", start
        )

        assert first == second

    def test_events_within_one_hour_are_adjacent(
        self, event_detector
    ):
        event1 = {
            "start_time": "2026-08-15T10:00:00+00:00",
            "end_time": "2026-08-15T11:00:00+00:00",
        }
        event2 = {
            "start_time": "2026-08-15T12:00:00+00:00",
            "end_time": "2026-08-15T13:00:00+00:00",
        }

        assert event_detector._events_are_adjacent(
            event1, event2
        ) is True

    def test_events_more_than_one_hour_apart_not_adjacent(
        self, event_detector
    ):
        event1 = {
            "start_time": "2026-08-15T10:00:00+00:00",
            "end_time": "2026-08-15T11:00:00+00:00",
        }
        event2 = {
            "start_time": "2026-08-15T13:00:00+00:00",
            "end_time": "2026-08-15T14:00:00+00:00",
        }

        assert event_detector._events_are_adjacent(
            event1, event2
        ) is False

    def test_merge_event_statistics(self, event_detector):
        event1 = {
            "event_id": "event1",
            "location_id": "kolkata",
            "pollutant": "pm25",
            "start_time": "2026-08-15T10:00:00+00:00",
            "end_time": "2026-08-15T11:00:00+00:00",
            "duration_hours": 2,
            "peak_value": 60.0,
            "mean_value": 50.0,
            "peak_anomaly_score": 3.0,
            "severity": "HIGH",
            "anomaly_count": 2,
        }

        event2 = {
            "event_id": "event2",
            "location_id": "kolkata",
            "pollutant": "pm25",
            "start_time": "2026-08-15T12:00:00+00:00",
            "end_time": "2026-08-15T13:00:00+00:00",
            "duration_hours": 2,
            "peak_value": 100.0,
            "mean_value": 80.0,
            "peak_anomaly_score": 5.0,
            "severity": "EXTREME",
            "anomaly_count": 2,
        }

        merged = event_detector._merge_two_events(
            event1, event2
        )

        assert merged["peak_value"] == 100.0
        assert merged["mean_value"] == pytest.approx(65.0)
        assert merged["peak_anomaly_score"] == 5.0
        assert merged["severity"] == "EXTREME"
        assert merged["anomaly_count"] == 4
        assert merged["duration_hours"] == 4

    def test_merge_events_with_missing_values(self, event_detector):
        event1 = {
            "event_id": "event1",
            "location_id": "kolkata",
            "pollutant": "pm25",
            "start_time": "2026-08-15T10:00:00+00:00",
            "end_time": "2026-08-15T11:00:00+00:00",
            "peak_value": None,
            "mean_value": None,
            "peak_anomaly_score": 3.0,
            "severity": "HIGH",
            "anomaly_count": 2,
        }

        event2 = {
            "event_id": "event2",
            "location_id": "kolkata",
            "pollutant": "pm25",
            "start_time": "2026-08-15T12:00:00+00:00",
            "end_time": "2026-08-15T13:00:00+00:00",
            "peak_value": 80.0,
            "mean_value": 80.0,
            "peak_anomaly_score": 4.0,
            "severity": "SEVERE",
            "anomaly_count": 2,
        }

        merged = event_detector._merge_two_events(
            event1, event2
        )

        assert merged["peak_value"] == 80.0
        assert merged["mean_value"] == 80.0
        assert merged["anomaly_count"] == 4
        assert merged["severity"] == "SEVERE"


class TestStationHealthScoring:
    """Test production station health scoring."""

    def test_healthy_station(self, health_scorer):
        score, penalties = health_scorer._calculate_health_score({
            "availability_pct": 100.0,
            "missing_rate": 0.0,
            "duplicate_rate": 0.0,
            "stale_rate": 0.0,
            "flatline_rate": 0.0,
            "outlier_rate": 0.0,
        })

        assert score == 100.0
        assert penalties == []
        assert health_scorer._classify_status(score) == "healthy"

    def test_degraded_station(self, health_scorer):
        score = health_scorer._classify_status(65.0)

        assert score == HealthStatus.DEGRADED.value

    def test_offline_station(self, health_scorer):
        score = health_scorer._classify_status(45.0)

        assert score == HealthStatus.OFFLINE.value

    def test_health_score_penalties(self, health_scorer):
        metrics = {
            "availability_pct": 70.0,
            "missing_rate": 15.0,
            "duplicate_rate": 8.0,
            "stale_rate": 7.0,
            "flatline_rate": 12.0,
            "outlier_rate": 3.0,
        }

        score, penalties = health_scorer._calculate_health_score(
            metrics
        )

        assert score == 15.0
        assert len(penalties) == 6
        assert health_scorer._classify_status(score) == "offline"

    def test_health_score_never_below_zero(self, health_scorer):
        metrics = {
            "availability_pct": 0.0,
            "missing_rate": 100.0,
            "duplicate_rate": 100.0,
            "stale_rate": 100.0,
            "flatline_rate": 100.0,
            "outlier_rate": 100.0,
        }

        score, _ = health_scorer._calculate_health_score(
            metrics
        )

        assert score == 0.0

    def test_health_score_threshold_boundaries(self, health_scorer):
        assert health_scorer._classify_status(80.0) == "healthy"
        assert health_scorer._classify_status(79.99) == "degraded"
        assert health_scorer._classify_status(50.0) == "degraded"
        assert health_scorer._classify_status(49.99) == "offline"

    def test_station_health_result(self, health_scorer):
        metrics = {
            "availability_pct": 98.0,
            "missing_rate": 2.0,
            "duplicate_rate": 1.0,
            "stale_rate": 0.0,
            "flatline_rate": 0.0,
            "outlier_rate": 0.0,
        }

        health_scorer._calculate_station_metrics = (
            lambda **kwargs: metrics
        )

        result = health_scorer.score_station_health(
            station_id="station_001",
            window_days=30,
            end_date=date(2026, 8, 15),
        )

        assert result["station_id"] == "station_001"
        assert result["window_days"] == 30
        assert result["health_score"] == 100.0
        assert result["status"] == "healthy"
        assert result["penalties_applied"] == []
        assert result["computed_at"] is not None

    def test_batch_station_health(self, health_scorer):
        results = health_scorer.score_batch(
            station_ids=["station_001", "station_002"],
            window_days=30,
            end_date=date(2026, 8, 15),
        )

        assert len(results) == 2
        assert results[0]["station_id"] == "station_001"
        assert results[1]["station_id"] == "station_002"

    def test_empty_health_summary(self, health_scorer):
        summary = health_scorer.get_health_summary([])

        assert summary["total_stations"] == 0
        assert summary["healthy"] == 0
        assert summary["degraded"] == 0
        assert summary["offline"] == 0
        assert summary["mean_health_score"] is None

    def test_health_summary_statistics(self, health_scorer):
        health_scores = [
            {"health_score": 90.0, "status": "healthy"},
            {"health_score": 60.0, "status": "degraded"},
            {"health_score": 40.0, "status": "offline"},
        ]

        summary = health_scorer.get_health_summary(
            health_scores
        )

        assert summary["total_stations"] == 3
        assert summary["healthy"] == 1
        assert summary["degraded"] == 1
        assert summary["offline"] == 1
        assert summary["mean_health_score"] == pytest.approx(
            190.0 / 3
        )
        assert summary["median_health_score"] == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
