
"""Unit tests for anomaly detection using robust statistics.

Tests robust Z-score calculation, severity classification,
zero-MAD handling, fallback logic, batch detection and summaries.
"""

from datetime import datetime, timezone

import pytest

from aq_engine.analytics.anomaly import (
    AnomalyDetector,
    AnomalySeverity,
)


@pytest.fixture
def detector():
    """Create an anomaly detector."""
    return AnomalyDetector()


@pytest.fixture
def sample_fact():
    """Provide a sample hourly observation."""
    return {
        "location_id": "kolkata",
        "pollutant": "pm25",
        "observed_value": 50.0,
        "hour_start": datetime(
            2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc
        ),
    }


@pytest.fixture
def sample_baseline():
    """Provide a historical baseline."""
    return {
        "historical_median": 40.0,
        "mad": 5.0,
        "p95": 60.0,
        "p99": 70.0,
    }


class TestRobustZScoreCalculation:
    """Test robust Z-score calculation."""

    def test_normal_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=42.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(0.2698, abs=0.001)
        assert severity == AnomalySeverity.NORMAL.value

    def test_elevated_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=58.5325,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(2.5)
        assert severity == AnomalySeverity.ELEVATED.value

    def test_high_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=65.9445,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(3.5, abs=0.001)
        assert severity == AnomalySeverity.HIGH.value

    def test_severe_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=73.3585,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(4.5, abs=0.001)
        assert severity == AnomalySeverity.SEVERE.value

    def test_extreme_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=84.478,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(6.0)
        assert severity == AnomalySeverity.EXTREME.value

    def test_negative_robust_z(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=15.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z < 0
        assert abs(robust_z) == pytest.approx(3.372)
        assert severity == AnomalySeverity.HIGH.value

    def test_negative_elevated_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=21.4675,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(-2.5)
        assert severity == AnomalySeverity.ELEVATED.value


class TestZeroMADEdgeCase:
    """Test handling of zero MAD."""

    def test_zero_mad_uses_fallback(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=50.0,
            baseline_median=40.0,
            baseline_mad=0.0,
        )

        assert robust_z == 3.0
        assert severity == AnomalySeverity.HIGH.value

    def test_value_twice_median_with_zero_mad(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=80.0,
            baseline_median=40.0,
            baseline_mad=0.0,
        )

        assert robust_z == 3.0
        assert severity == AnomalySeverity.HIGH.value

    def test_zero_median_zero_mad_with_large_value(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=150.0,
            baseline_median=0.0,
            baseline_mad=0.0,
        )

        assert robust_z == 5.0
        assert severity == AnomalySeverity.EXTREME.value

    def test_zero_median_and_zero_observation(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=0.0,
            baseline_median=0.0,
            baseline_mad=0.0,
        )

        assert robust_z == 0.0
        assert severity == AnomalySeverity.NORMAL.value

    def test_zero_mad_below_baseline(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=20.0,
            baseline_median=40.0,
            baseline_mad=0.0,
        )

        assert robust_z == -3.0
        assert severity == AnomalySeverity.HIGH.value

    def test_zero_mad_exact_baseline(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0,
            baseline_median=40.0,
            baseline_mad=0.0,
        )

        assert robust_z == 0.0
        assert severity == AnomalySeverity.NORMAL.value


class TestFullAnomalyDetection:
    """Test complete anomaly detection flow."""

    def test_normal_observation(
        self, detector, sample_fact, sample_baseline
    ):
        sample_fact["observed_value"] = 42.0

        result = detector.detect_anomalies(
            sample_fact, sample_baseline
        )

        assert result["location_id"] == "kolkata"
        assert result["pollutant"] == "pm25"
        assert result["severity"] == AnomalySeverity.NORMAL.value
        assert result["fallback_used"] is False
        assert result["fallback_reason"] is None

    def test_anomalous_observation(
        self, detector, sample_fact, sample_baseline
    ):
        sample_fact["observed_value"] = 73.0

        result = detector.detect_anomalies(
            sample_fact, sample_baseline
        )

        assert result["severity"] == AnomalySeverity.SEVERE.value
        assert result["robust_z"] == pytest.approx(
            (73.0 - 40.0) / (1.4826 * 5.0)
        )
        assert result["fallback_used"] is False

    def test_missing_baseline_uses_citywide_fallback(
        self, detector, sample_fact
    ):
        fallback_baselines = {
            ("citywide", "pm25"): {
                "historical_median": 45.0,
                "mad": 5.0,
            }
        }

        result = detector.detect_anomalies(
            hourly_fact=sample_fact,
            baseline=None,
            fallback_baselines=fallback_baselines,
        )

        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "citywide_fallback"
        assert result["baseline_median"] == 45.0
        assert result["baseline_mad"] == 5.0

    def test_missing_baseline_uses_recent_fallback(
        self, detector, sample_fact
    ):
        fallback_baselines = {
            ("recent_7d", "pm25"): {
                "historical_median": 48.0,
                "mad": 4.0,
            }
        }

        result = detector.detect_anomalies(
            hourly_fact=sample_fact,
            baseline=None,
            fallback_baselines=fallback_baselines,
        )

        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "recent_7day_fallback"
        assert result["baseline_median"] == 48.0

    def test_citywide_fallback_has_priority(
        self, detector, sample_fact
    ):
        fallback_baselines = {
            ("citywide", "pm25"): {
                "historical_median": 50.0,
                "mad": 5.0,
            },
            ("recent_7d", "pm25"): {
                "historical_median": 45.0,
                "mad": 4.0,
            },
        }

        result = detector.detect_anomalies(
            hourly_fact=sample_fact,
            baseline=None,
            fallback_baselines=fallback_baselines,
        )

        assert result["baseline_median"] == 50.0
        assert result["fallback_reason"] == "citywide_fallback"

    def test_no_baseline_available(
        self, detector, sample_fact
    ):
        result = detector.detect_anomalies(
            hourly_fact=sample_fact,
            baseline=None,
            fallback_baselines=None,
        )

        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "no_baseline_available"
        assert result["severity"] == AnomalySeverity.NORMAL.value
        assert result["robust_z"] is None
        assert result["baseline_median"] is None
        assert result["baseline_mad"] is None

    def test_baseline_with_missing_median_uses_fallback(
        self, detector, sample_fact
    ):
        fallback_baselines = {
            ("citywide", "pm25"): {
                "historical_median": 45.0,
                "mad": 5.0,
            }
        }

        result = detector.detect_anomalies(
            hourly_fact=sample_fact,
            baseline={"historical_median": None, "mad": 0.0},
            fallback_baselines=fallback_baselines,
        )

        assert result["fallback_used"] is True
        assert result["baseline_median"] == 45.0

    def test_result_contains_required_fields(
        self, detector, sample_fact, sample_baseline
    ):
        result = detector.detect_anomalies(
            sample_fact, sample_baseline
        )

        required_fields = {
            "location_id",
            "pollutant",
            "hour_start",
            "observed_value",
            "baseline_median",
            "baseline_mad",
            "robust_z",
            "severity",
            "fallback_used",
            "fallback_reason",
            "detected_at",
        }

        assert required_fields.issubset(result.keys())

    def test_datetime_is_serialized_to_iso_format(
        self, detector, sample_fact, sample_baseline
    ):
        result = detector.detect_anomalies(
            sample_fact, sample_baseline
        )

        assert result["hour_start"] == (
            "2026-08-15T12:00:00+00:00"
        )

        detected_at = datetime.fromisoformat(
            result["detected_at"]
        )
        assert detected_at.tzinfo is not None


class TestBatchDetection:
    """Test batch anomaly detection."""

    def test_batch_detection(self, detector):
        facts = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "observed_value": 42.0,
                "hour_start": datetime(
                    2026, 8, 15, 12, 0, tzinfo=timezone.utc
                ),
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "observed_value": 80.0,
                "hour_start": datetime(
                    2026, 8, 15, 13, 0, tzinfo=timezone.utc
                ),
            },
        ]

        baselines = {
            ("kolkata", "pm25"): {
                "historical_median": 40.0,
                "mad": 5.0,
            }
        }

        results = detector.detect_batch(facts, baselines)

        assert len(results) == 2
        assert results[0]["severity"] == AnomalySeverity.NORMAL.value
        assert results[1]["severity"] == AnomalySeverity.HIGH.value

    def test_empty_batch(self, detector):
        results = detector.detect_batch([], {})

        assert results == []

    def test_batch_with_multiple_pollutants(self, detector):
        facts = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "observed_value": 42.0,
                "hour_start": datetime(
                    2026, 8, 15, 12, 0, tzinfo=timezone.utc
                ),
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm10",
                "observed_value": 100.0,
                "hour_start": datetime(
                    2026, 8, 15, 13, 0, tzinfo=timezone.utc
                ),
            },
        ]

        baselines = {
            ("kolkata", "pm25"): {
                "historical_median": 40.0,
                "mad": 5.0,
            },
            ("kolkata", "pm10"): {
                "historical_median": 50.0,
                "mad": 10.0,
            },
        }

        results = detector.detect_batch(facts, baselines)

        assert len(results) == 2
        assert results[0]["severity"] == AnomalySeverity.NORMAL.value
        assert results[1]["severity"] == AnomalySeverity.HIGH.value


class TestAnomalySummary:
    """Test anomaly summary statistics."""

    def test_summary_with_mixed_severities(self, detector):
        results = [
            {"severity": AnomalySeverity.NORMAL.value},
            {"severity": AnomalySeverity.NORMAL.value},
            {"severity": AnomalySeverity.ELEVATED.value},
            {"severity": AnomalySeverity.HIGH.value},
            {"severity": AnomalySeverity.SEVERE.value},
            {"severity": AnomalySeverity.EXTREME.value},
        ]

        summary = detector.get_anomaly_summary(results)

        assert summary["total_checked"] == 6
        assert summary["total_anomalies"] == 4
        assert summary["normal"] == 2
        assert summary["elevated"] == 1
        assert summary["high"] == 1
        assert summary["severe"] == 1
        assert summary["extreme"] == 1
        assert summary["anomaly_rate"] == pytest.approx(4 / 6)

    def test_summary_empty_list(self, detector):
        summary = detector.get_anomaly_summary([])

        assert summary["total_checked"] == 0
        assert summary["total_anomalies"] == 0
        assert summary["normal"] == 0
        assert summary["elevated"] == 0
        assert summary["high"] == 0
        assert summary["severe"] == 0
        assert summary["extreme"] == 0
        assert "anomaly_rate" not in summary

    def test_summary_with_only_normal_observations(self, detector):
        results = [
            {"severity": AnomalySeverity.NORMAL.value},
            {"severity": AnomalySeverity.NORMAL.value},
        ]

        summary = detector.get_anomaly_summary(results)

        assert summary["total_checked"] == 2
        assert summary["total_anomalies"] == 0
        assert summary["anomaly_rate"] == 0.0


class TestSeverityThresholds:
    """Test severity threshold boundaries."""

    @pytest.mark.parametrize(
        ("z_score", "expected_severity"),
        [
            (1.99, AnomalySeverity.NORMAL.value),
            (2.0, AnomalySeverity.ELEVATED.value),
            (2.99, AnomalySeverity.ELEVATED.value),
            (3.0, AnomalySeverity.HIGH.value),
            (3.99, AnomalySeverity.HIGH.value),
            (4.0, AnomalySeverity.SEVERE.value),
            (4.99, AnomalySeverity.SEVERE.value),
            (5.0, AnomalySeverity.EXTREME.value),
            (6.0, AnomalySeverity.EXTREME.value),
        ],
    )
    def test_severity_thresholds(
        self, detector, z_score, expected_severity
    ):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0 + z_score * 1.4826 * 5.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(z_score)
        assert severity == expected_severity

    def test_negative_threshold_classification(self, detector):
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0 - 3.0 * 1.4826 * 5.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert robust_z == pytest.approx(-3.0)
        assert severity == AnomalySeverity.HIGH.value


class TestFallbackLogic:
    """Test fallback baseline selection."""

    def test_citywide_fallback_preferred(self, detector):
        fallback_baselines = {
            ("citywide", "pm25"): {
                "historical_median": 50.0,
                "mad": 5.0,
            },
            ("recent_7d", "pm25"): {
                "historical_median": 45.0,
                "mad": 4.0,
            },
        }

        baseline, reason = detector._get_fallback_baseline(
            "kolkata",
            "pm25",
            fallback_baselines,
        )

        assert baseline["historical_median"] == 50.0
        assert reason == "citywide_fallback"

    def test_recent_fallback_when_citywide_missing(self, detector):
        fallback_baselines = {
            ("recent_7d", "pm25"): {
                "historical_median": 45.0,
                "mad": 4.0,
            }
        }

        baseline, reason = detector._get_fallback_baseline(
            "kolkata",
            "pm25",
            fallback_baselines,
        )

        assert baseline["historical_median"] == 45.0
        assert reason == "recent_7day_fallback"

    def test_no_fallback_available(self, detector):
        baseline, reason = detector._get_fallback_baseline(
            "kolkata",
            "pm25",
            {},
        )

        assert baseline is None
        assert reason == "no_fallback_available"

    def test_none_fallback_dictionary(self, detector):
        baseline, reason = detector._get_fallback_baseline(
            "kolkata",
            "pm25",
            None,
        )

        assert baseline is None
        assert reason == "no_fallback_available"

    def test_fallback_for_different_pollutant_is_not_used(self, detector):
        fallback_baselines = {
            ("citywide", "pm10"): {
                "historical_median": 50.0,
                "mad": 5.0,
            }
        }

        baseline, reason = detector._get_fallback_baseline(
            "kolkata",
            "pm25",
            fallback_baselines,
        )

        assert baseline is None
        assert reason == "no_fallback_available"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
