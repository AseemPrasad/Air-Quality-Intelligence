
import math

from aq_engine.analytics.anomaly import AnomalyDetector, AnomalySeverity


def test_zero_mad_zero_median_flags_nonzero_spike():
    """A non-zero reading against a flat zero baseline is anomalous."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=15.0,
        baseline_median=0.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 3.0
    assert severity == AnomalySeverity.HIGH.value


def test_zero_mad_matching_zero_baseline_is_normal():
    """A reading equal to a zero baseline must remain normal."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=0.0,
        baseline_median=0.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 0.0
    assert severity == AnomalySeverity.NORMAL.value


def test_zero_mad_large_spike_is_extreme():
    """A reading above 100 against a zero baseline is extreme."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=150.0,
        baseline_median=0.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 5.0
    assert severity == AnomalySeverity.EXTREME.value


def test_zero_mad_nonzero_constant_baseline_flags_positive_deviation():
    """A positive deviation from a constant baseline is anomalous."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=65.0,
        baseline_median=55.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 3.0
    assert severity == AnomalySeverity.HIGH.value


def test_zero_mad_negative_deviation_is_anomalous():
    """A negative deviation from a constant baseline is also detected."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=45.0,
        baseline_median=55.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == -3.0
    assert severity == AnomalySeverity.HIGH.value


def test_zero_mad_matching_nonzero_baseline_is_normal():
    """A reading equal to a constant non-zero baseline is normal."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=55.0,
        baseline_median=55.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 0.0
    assert severity == AnomalySeverity.NORMAL.value
