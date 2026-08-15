"""Anomaly detection using robust statistics (MAD-based Z-score).

Detects anomalous observations using Median Absolute Deviation (MAD)
for robustness to historical outliers, with fallback logic for edge cases.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List
from enum import Enum

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class AnomalySeverity(str, Enum):
    """Anomaly severity classification."""

    NORMAL = "NORMAL"  # |z| < 2.0
    ELEVATED = "ELEVATED"  # 2.0 <= |z| < 3.0
    HIGH = "HIGH"  # 3.0 <= |z| < 4.0
    SEVERE = "SEVERE"  # 4.0 <= |z| < 5.0
    EXTREME = "EXTREME"  # |z| >= 5.0


class AnomalyDetector:
    """Detects anomalous observations using robust statistics.

    Uses Median Absolute Deviation (MAD) to calculate robust Z-score,
    which is more resilient to historical outliers than standard Z-score.

    Formula: robust_z = (x - median) / (1.4826 * MAD)

    Edge cases:
    - MAD = 0 (constant history): Use percentile rank fallback
    - Missing baseline: Use city-wide median or 7-day recent median

    Example:
        >>> detector = AnomalyDetector()
        >>> fact = {
        ...     "location_id": "kolkata",
        ...     "observed_value": 150.0,
        ...     "pollutant": "pm25"
        ... }
        >>> baseline = {
        ...     "historical_median": 50.0,
        ...     "mad": 10.0
        ... }
        >>> result = detector.detect_anomalies(fact, baseline)
        >>> print(f"Severity: {result['severity']}")
    """

    # Z-score thresholds for severity classification
    SEVERITY_THRESHOLDS = {
        AnomalySeverity.NORMAL: 2.0,  # |z| < 2.0
        AnomalySeverity.ELEVATED: 2.0,  # 2.0 <= |z| < 3.0
        AnomalySeverity.HIGH: 3.0,  # 3.0 <= |z| < 4.0
        AnomalySeverity.SEVERE: 4.0,  # 4.0 <= |z| < 5.0
        AnomalySeverity.EXTREME: 5.0,  # |z| >= 5.0
    }

    # MAD constant for converting MAD to standard deviation
    MAD_CONSTANT = 1.4826

    def __init__(self):
        """Initialize anomaly detector."""
        pass

    def detect_anomalies(
        self,
        hourly_fact: Dict[str, Any],
        baseline: Optional[Dict[str, Any]] = None,
        fallback_baselines: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Detect anomalies in hourly observations.

        Args:
            hourly_fact: Hourly fact dict with location_id, pollutant, observed_value, hour_start
            baseline: Baseline dict with historical_median, mad, (optional) p95, p99
            fallback_baselines: Fallback baselines (city-wide or recent) if primary is missing

        Returns:
            Dict with:
            - location_id, pollutant, hour_start
            - observed_value, baseline_median, baseline_mad
            - robust_z (z-score or percentile rank)
            - severity (NORMAL, ELEVATED, HIGH, SEVERE, EXTREME)
            - fallback_used (bool), fallback_reason (str)
            - detected_at (timestamp)
        """
        location_id = hourly_fact.get("location_id")
        pollutant = hourly_fact.get("pollutant")
        observed_value = hourly_fact.get("observed_value")
        hour_start = hourly_fact.get("hour_start")

        logger.debug(
            f"Detecting anomalies for {location_id}/{pollutant} at {hour_start}: {observed_value}"
        )

        # Handle missing baseline
        if baseline is None or baseline.get("historical_median") is None:
            baseline, fallback_reason = self._get_fallback_baseline(
                location_id, pollutant, fallback_baselines
            )
            fallback_used = True
        else:
            fallback_used = False
            fallback_reason = None

        if baseline is None:
            # No baseline available at all
            logger.warning(
                f"No baseline available for {location_id}/{pollutant}; cannot detect anomalies"
            )
            return self._empty_anomaly_result(
                location_id, pollutant, hour_start, observed_value,
                fallback_used=True, fallback_reason="no_baseline_available"
            )

        baseline_median = baseline.get("historical_median")
        baseline_mad = baseline.get("mad", 0.0)

        # Calculate robust Z-score
        robust_z, severity = self._calculate_robust_z_and_severity(
            observed_value=observed_value,
            baseline_median=baseline_median,
            baseline_mad=baseline_mad,
        )

        result = {
            "location_id": location_id,
            "pollutant": pollutant,
            "hour_start": hour_start.isoformat() if isinstance(hour_start, datetime) else hour_start,
            "observed_value": observed_value,
            "baseline_median": baseline_median,
            "baseline_mad": baseline_mad,
            "robust_z": robust_z,
            "severity": severity,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        if severity != AnomalySeverity.NORMAL:
            logger.info(
                f"Anomaly detected: {location_id}/{pollutant} at {hour_start} "
                f"value={observed_value:.1f} (z={robust_z:.2f}, severity={severity})"
            )

        return result

    def detect_batch(
        self,
        hourly_facts: List[Dict[str, Any]],
        baselines: Dict[str, Dict[str, Any]],
        fallback_baselines: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Detect anomalies for batch of hourly facts.

        Args:
            hourly_facts: List of hourly fact dicts
            baselines: Dict mapping (location_id, pollutant) → baseline dict
            fallback_baselines: Fallback baselines

        Returns:
            List of anomaly result dicts
        """
        results = []
        for fact in hourly_facts:
            key = (fact.get("location_id"), fact.get("pollutant"))
            baseline = baselines.get(key)

            result = self.detect_anomalies(
                hourly_fact=fact,
                baseline=baseline,
                fallback_baselines=fallback_baselines,
            )
            results.append(result)

        return results

    def _calculate_robust_z_and_severity(
        self,
        observed_value: float,
        baseline_median: float,
        baseline_mad: float,
    ) -> tuple:
        """Calculate robust Z-score and classify severity.

        Args:
            observed_value: Observed concentration
            baseline_median: Historical median
            baseline_mad: Median Absolute Deviation

        Returns:
            Tuple of (robust_z, severity_string)
        """
        if baseline_mad == 0:
            # Constant historical data: use percentile fallback
            robust_z = self._calculate_percentile_rank_as_zscore(
                observed_value, baseline_median
            )
            logger.debug(
                f"MAD is zero (constant history); using percentile rank as z-score: {robust_z:.2f}"
            )
        else:
            # Normal robust Z-score
            robust_z = (observed_value - baseline_median) / (self.MAD_CONSTANT * baseline_mad)

        # Take absolute value for severity classification
        abs_z = abs(robust_z)

        # Classify severity
        if abs_z < self.SEVERITY_THRESHOLDS[AnomalySeverity.NORMAL]:
            severity = AnomalySeverity.NORMAL.value
        elif abs_z < self.SEVERITY_THRESHOLDS[AnomalySeverity.HIGH]:
            severity = AnomalySeverity.ELEVATED.value
        elif abs_z < self.SEVERITY_THRESHOLDS[AnomalySeverity.SEVERE]:
            severity = AnomalySeverity.HIGH.value
        elif abs_z < self.SEVERITY_THRESHOLDS[AnomalySeverity.EXTREME]:
            severity = AnomalySeverity.SEVERE.value
        else:
            severity = AnomalySeverity.EXTREME.value

        return robust_z, severity

    @staticmethod
    def _calculate_percentile_rank_as_zscore(
        observed_value: float, baseline_median: float
    ) -> float:
        """Calculate percentile rank and convert to approximate Z-score.

        Used when MAD is zero (constant historical data).
        If observed_value is significantly above/below median, consider anomalous.

        Args:
            observed_value: Observed value
            baseline_median: Historical median

        Returns:
            Approximate Z-score based on distance from median
        """
        # Simple heuristic: if value is much higher/lower than median,
        # it's anomalous. Without historical variance, use a threshold.
        # E.g., if value is 2x the median, flag as anomalous.

        if baseline_median == 0:
            # Special case: if median is 0, use absolute difference
            if abs(observed_value) > 100:  # Arbitrary threshold
                return 5.0  # EXTREME
            else:
                return 0.0  # NORMAL
        else:
            ratio = observed_value / baseline_median
            if ratio >= 2.0 or ratio <= 0.5:
                # Value is significantly different from historical median
                return 3.0 if ratio >= 2.0 else -3.0  # HIGH severity
            else:
                return 0.0  # NORMAL

    def _get_fallback_baseline(
        self,
        location_id: str,
        pollutant: str,
        fallback_baselines: Optional[Dict[str, Any]],
    ) -> tuple:
        """Get fallback baseline when primary is missing.

        Strategy:
        1. Check city-wide baseline (median across all stations)
        2. Check 7-day recent median
        3. Return None if no fallback available

        Args:
            location_id: Location identifier
            pollutant: Pollutant name
            fallback_baselines: Fallback baseline dict

        Returns:
            Tuple of (baseline_dict, fallback_reason)
        """
        if fallback_baselines is None:
            return None, "no_fallback_available"

        # Try city-wide baseline
        citywide_key = ("citywide", pollutant)
        if citywide_key in fallback_baselines:
            logger.info(
                f"Using city-wide baseline fallback for {location_id}/{pollutant}"
            )
            return fallback_baselines[citywide_key], "citywide_fallback"

        # Try recent 7-day baseline
        recent_key = ("recent_7d", pollutant)
        if recent_key in fallback_baselines:
            logger.info(
                f"Using 7-day recent baseline fallback for {location_id}/{pollutant}"
            )
            return fallback_baselines[recent_key], "recent_7day_fallback"

        return None, "no_fallback_available"

    @staticmethod
    def _empty_anomaly_result(
        location_id: str,
        pollutant: str,
        hour_start,
        observed_value: float,
        fallback_used: bool = False,
        fallback_reason: str = None,
    ) -> Dict[str, Any]:
        """Create empty anomaly result (when baseline unavailable).

        Args:
            location_id: Location
            pollutant: Pollutant
            hour_start: Hour timestamp
            observed_value: Observed value
            fallback_used: Whether fallback was attempted
            fallback_reason: Reason for fallback

        Returns:
            Dict with None for calculated fields
        """
        return {
            "location_id": location_id,
            "pollutant": pollutant,
            "hour_start": hour_start.isoformat() if isinstance(hour_start, datetime) else hour_start,
            "observed_value": observed_value,
            "baseline_median": None,
            "baseline_mad": None,
            "robust_z": None,
            "severity": AnomalySeverity.NORMAL.value,  # Default to NORMAL if unknown
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_anomaly_summary(
        self,
        anomaly_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Get summary statistics from anomaly detection results.

        Args:
            anomaly_results: List of anomaly result dicts

        Returns:
            Dict with summary metrics
        """
        if not anomaly_results:
            return {
                "total_checked": 0,
                "total_anomalies": 0,
                "normal": 0,
                "elevated": 0,
                "high": 0,
                "severe": 0,
                "extreme": 0,
            }

        severities = [r["severity"] for r in anomaly_results]

        return {
            "total_checked": len(anomaly_results),
            "total_anomalies": sum(1 for s in severities if s != AnomalySeverity.NORMAL.value),
            "normal": severities.count(AnomalySeverity.NORMAL.value),
            "elevated": severities.count(AnomalySeverity.ELEVATED.value),
            "high": severities.count(AnomalySeverity.HIGH.value),
            "severe": severities.count(AnomalySeverity.SEVERE.value),
            "extreme": severities.count(AnomalySeverity.EXTREME.value),
            "anomaly_rate": sum(
                1 for s in severities if s != AnomalySeverity.NORMAL.value
            ) / len(severities) if anomaly_results else 0.0,
        }
