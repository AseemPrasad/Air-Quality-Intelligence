import math

from aq_engine.analytics.anomaly import AnomalyDetector, AnomalySeverity


def test_zero_mad_zero_median_flags_nonzero_spike():
    """A non-zero reading must be detected against a flat zero baseline."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=15.0,
        baseline_median=0.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 3.0
    assert severity == AnomalySeverity.HIGH.value


def test_zero_mad_matching_baseline_is_normal():
    """A reading equal to a constant baseline must remain normal."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=0.0,
        baseline_median=0.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == 0.0
    assert severity == AnomalySeverity.NORMAL.value


def test_zero_mad_nonzero_constant_baseline_flags_deviation():
    """A deviation from a constant non-zero baseline is anomalous."""
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
    """Negative deviations from a constant baseline are also detected."""
    detector = AnomalyDetector()

    robust_z, severity = detector._calculate_robust_z_and_severity(
        observed_value=45.0,
        baseline_median=55.0,
        baseline_mad=0.0,
    )

    assert math.isfinite(robust_z)
    assert robust_z == -3.0
    assert severity == AnomalySeverity.HIGH.value
