"""Unit tests for anomaly detection using robust statistics.

Tests anomaly detection algorithms, severity classification, and fallback logic.
"""

import pytest
from datetime import datetime, timezone, date
from unittest.mock import Mock, patch

from aq_engine.analytics.anomaly import AnomalyDetector, AnomalySeverity


@pytest.fixture
def detector():
    """AnomalyDetector instance."""
    return AnomalyDetector()


@pytest.fixture
def sample_fact():
    """Sample hourly fact."""
    return {
        "location_id": "kolkata",
        "pollutant": "pm25",
        "observed_value": 50.0,
        "hour_start": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
    }


@pytest.fixture
def sample_baseline():
    """Sample baseline with MAD."""
    return {
        "historical_median": 40.0,
        "mad": 5.0,
        "p95": 60.0,
        "p99": 70.0,
    }


class TestRobustZScoreCalculation:
    """Test robust Z-score calculation."""

    def test_normal_observation_near_median(self, detector, sample_fact, sample_baseline):
        """Test normal observation near baseline median."""
        sample_fact["observed_value"] = 42.0  # Close to median 40

        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=42.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        # z = (42 - 40) / (1.4826 * 5) = 2 / 7.413 ≈ 0.27
        assert abs(robust_z) < 2.0
        assert severity == AnomalySeverity.NORMAL.value

    def test_elevated_observation_2_to_3_std(self, detector):
        """Test elevated observation (2-3 MAD from median)."""
        # z = (45 - 40) / (1.4826 * 5) = 5 / 7.413 ≈ 0.675 (normal range)
        # To get z ≈ 2.5, need value = median + 2.5 * 1.4826 * 5 = 40 + 18.5325 ≈ 58.5
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=58.5,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        # z ≈ 2.5
        assert 2.0 <= abs(robust_z) < 3.0
        assert severity == AnomalySeverity.ELEVATED.value

    def test_high_observation_3_to_4_std(self, detector):
        """Test high observation (3-4 MAD from median)."""
        # value = 40 + 3.5 * 1.4826 * 5 = 40 + 25.945 ≈ 65.9
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=65.9,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        # z ≈ 3.5
        assert 3.0 <= abs(robust_z) < 4.0
        assert severity == AnomalySeverity.HIGH.value

    def test_severe_observation_4_to_5_std(self, detector):
        """Test severe observation (4-5 MAD from median)."""
        # value = 40 + 4.5 * 1.4826 * 5 = 40 + 33.358 ≈ 73.4
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=73.4,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        # z ≈ 4.5
        assert 4.0 <= abs(robust_z) < 5.0
        assert severity == AnomalySeverity.SEVERE.value

    def test_extreme_observation_5_plus_std(self, detector):
        """Test extreme observation (>5 MAD from median)."""
        # value = 40 + 6 * 1.4826 * 5 = 40 + 44.478 ≈ 84.5
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=84.5,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        # z ≈ 6
        assert abs(robust_z) >= 5.0
        assert severity == AnomalySeverity.EXTREME.value

    def test_negative_robust_z(self, detector):
        """Test negative robust Z (value below median)."""
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=15.0,  # Well below median 40
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        # z = (15 - 40) / (1.4826 * 5) = -25 / 7.413 ≈ -3.37
        assert robust_z < 0
        assert abs(robust_z) >= 3.0  # Should be HIGH severity by absolute value


class TestZeroMADEdgeCase:
    """Test handling when MAD is zero (constant historical data)."""

    def test_zero_mad_uses_percentile_fallback(self, detector):
        """Test zero MAD triggers percentile rank fallback."""
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=50.0,
            baseline_median=40.0,
            baseline_mad=0.0,  # Constant history
        )

        # With zero MAD, falls back to percentile logic
        # Since value (50) > median (40) by 1.25x, should be flagged
        assert robust_z is not None
        assert severity is not None

    def test_value_2x_median_with_zero_mad(self, detector):
        """Test value 2x median with zero MAD → anomalous."""
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=80.0,  # 2x median
            baseline_median=40.0,
            baseline_mad=0.0,
        )

        # Value is 2x median, should be flagged as HIGH
        assert abs(robust_z) >= 3.0
        assert severity == AnomalySeverity.HIGH.value

    def test_zero_median_zero_mad_with_value(self, detector):
        """Test zero median and zero MAD with nonzero value."""
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=150.0,
            baseline_median=0.0,
            baseline_mad=0.0,
        )

        # Value is high and median is zero, should be EXTREME
        assert robust_z >= 5.0
        assert severity == AnomalySeverity.EXTREME.value


class TestFullAnomalyDetection:
    """Test full anomaly detection flow."""

    def test_normal_observation_returns_normal_severity(self, detector, sample_fact, sample_baseline):
        """Test normal observation classified as NORMAL."""
        sample_fact["observed_value"] = 42.0

        result = detector.detect_anomalies(sample_fact, sample_baseline)

        assert result["location_id"] == "kolkata"
        assert result["pollutant"] == "pm25"
        assert result["severity"] == AnomalySeverity.NORMAL.value
        assert result["fallback_used"] is False

    def test_anomalous_observation_returns_severity(self, detector, sample_fact, sample_baseline):
        """Test anomalous observation classified correctly."""
        sample_fact["observed_value"] = 73.0  # About 4.5 MAD above median

        result = detector.detect_anomalies(sample_fact, sample_baseline)

        assert result["severity"] in [
            AnomalySeverity.SEVERE.value,
            AnomalySeverity.EXTREME.value,
        ]
        assert result["robust_z"] is not None

    def test_missing_baseline_uses_fallback(self, detector, sample_fact):
        """Test missing baseline triggers fallback."""
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

    def test_no_baseline_returns_normal_severity(self, detector, sample_fact):
        """Test no baseline available defaults to NORMAL."""
        result = detector.detect_anomalies(
            hourly_fact=sample_fact,
            baseline=None,
            fallback_baselines=None,
        )

        assert result["fallback_used"] is True
        assert result["fallback_reason"] == "no_baseline_available"
        assert result["severity"] == AnomalySeverity.NORMAL.value

    def test_7day_recent_fallback(self, detector, sample_fact):
        """Test 7-day recent fallback when city-wide unavailable."""
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


class TestBatchDetection:
    """Test batch anomaly detection."""

    def test_batch_detection(self, detector):
        """Test detecting anomalies for multiple observations."""
        facts = [
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "observed_value": 42.0,
                "hour_start": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            },
            {
                "location_id": "kolkata",
                "pollutant": "pm25",
                "observed_value": 80.0,
                "hour_start": datetime(2026, 8, 15, 13, 0, 0, tzinfo=timezone.utc),
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
        assert results[0]["severity"] == AnomalySeverity.NORMAL.value  # 42 is normal
        assert results[1]["severity"] != AnomalySeverity.NORMAL.value  # 80 is anomalous


class TestAnomalySummary:
    """Test anomaly summary statistics."""

    def test_summary_with_mixed_severities(self, detector):
        """Test summary calculation."""
        results = [
            {"severity": AnomalySeverity.NORMAL.value},
            {"severity": AnomalySeverity.NORMAL.value},
            {"severity": AnomalySeverity.ELEVATED.value},
            {"severity": AnomalySeverity.EXTREME.value},
        ]

        summary = detector.get_anomaly_summary(results)

        assert summary["total_checked"] == 4
        assert summary["total_anomalies"] == 2  # ELEVATED + EXTREME
        assert summary["normal"] == 2
        assert summary["elevated"] == 1
        assert summary["extreme"] == 1
        assert summary["anomaly_rate"] == pytest.approx(0.5, abs=0.01)

    def test_summary_empty_list(self, detector):
        """Test summary with empty results."""
        summary = detector.get_anomaly_summary([])

        assert summary["total_checked"] == 0
        assert summary["total_anomalies"] == 0


class TestSeverityThresholds:
    """Test severity threshold boundaries."""

    def test_normal_threshold_at_2(self, detector):
        """Test NORMAL threshold at z=2.0."""
        # At z=2.0: should be ELEVATED (boundary)
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0 + 2.0 * 1.4826 * 5.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert abs(robust_z) >= 2.0
        assert severity == AnomalySeverity.ELEVATED.value

    def test_high_threshold_at_3(self, detector):
        """Test HIGH threshold at z=3.0."""
        # At z=3.0: should be HIGH
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0 + 3.0 * 1.4826 * 5.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert abs(robust_z) >= 3.0
        assert severity == AnomalySeverity.HIGH.value

    def test_severe_threshold_at_4(self, detector):
        """Test SEVERE threshold at z=4.0."""
        # At z=4.0: should be SEVERE
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0 + 4.0 * 1.4826 * 5.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert abs(robust_z) >= 4.0
        assert severity == AnomalySeverity.SEVERE.value

    def test_extreme_threshold_at_5(self, detector):
        """Test EXTREME threshold at z=5.0."""
        # At z=5.0: should be EXTREME
        robust_z, severity = detector._calculate_robust_z_and_severity(
            observed_value=40.0 + 5.0 * 1.4826 * 5.0,
            baseline_median=40.0,
            baseline_mad=5.0,
        )

        assert abs(robust_z) >= 5.0
        assert severity == AnomalySeverity.EXTREME.value


class TestFallbackLogic:
    """Test fallback selection."""

    def test_citywide_fallback_preferred(self, detector):
        """Test city-wide baseline used when available."""
        fallback_baselines = {
            ("citywide", "pm25"): {"historical_median": 50.0, "mad": 5.0},
            ("recent_7d", "pm25"): {"historical_median": 45.0, "mad": 4.0},
        }

        baseline, reason = detector._get_fallback_baseline(
            "kolkata", "pm25", fallback_baselines
        )

        assert baseline["historical_median"] == 50.0
        assert reason == "citywide_fallback"

    def test_recent_fallback_when_citywide_missing(self, detector):
        """Test 7-day fallback when city-wide unavailable."""
        fallback_baselines = {
            ("recent_7d", "pm25"): {"historical_median": 45.0, "mad": 4.0}
        }

        baseline, reason = detector._get_fallback_baseline(
            "kolkata", "pm25", fallback_baselines
        )

        assert baseline["historical_median"] == 45.0
        assert reason == "recent_7day_fallback"

    def test_no_fallback_available(self, detector):
        """Test no fallback returns None."""
        baseline, reason = detector._get_fallback_baseline(
            "kolkata", "pm25", fallback_baselines={}
        )

        assert baseline is None
        assert reason == "no_fallback_available"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
