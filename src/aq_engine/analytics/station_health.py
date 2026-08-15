"""Station health scoring based on data quality metrics.

Evaluates station reliability and data quality over rolling windows,
providing actionable health status and recommendations for exclusion.
"""

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Station health status classification."""

    HEALTHY = "healthy"  # health_score >= 80
    DEGRADED = "degraded"  # 50 <= health_score < 80
    OFFLINE = "offline"  # health_score < 50


class StationHealthScorer:
    """Scores station health based on data quality metrics.

    Health score ranges 0-100 based on:
    - Availability: % of hours with at least one observation
    - Missing data: % of missing hourly records
    - Duplicate rate: % of records that are duplicates
    - Stale data: % of observations marked as stale
    - Flatline: % of consecutive identical values
    - Outliers: % of extreme observations (z-score > 5)

    Status classification:
    - >= 80: healthy (acceptable for dashboards)
    - 50-79: degraded (may have gaps or quality issues)
    - < 50: offline (recommend exclusion)

    Example:
        >>> scorer = StationHealthScorer()
        >>> health = scorer.score_station_health(
        ...     station_id="station_123",
        ...     window_days=30
        ... )
        >>> print(f"Status: {health['status']}")
        >>> print(f"Score: {health['health_score']:.1f}")
    """

    # Penalty matrix (penalties deducted from base_score=100)
    PENALTIES = {
        "low_availability": {
            "threshold": 80.0,  # % availability
            "penalty": 30,  # points
            "description": "Availability < 80%",
        },
        "high_missing_rate": {
            "threshold": 10.0,  # % missing
            "penalty": 20,
            "description": "Missing rate > 10%",
        },
        "high_duplicate_rate": {
            "threshold": 5.0,  # % duplicates
            "penalty": 10,
            "description": "Duplicate rate > 5%",
        },
        "high_stale_rate": {
            "threshold": 5.0,  # % stale
            "penalty": 10,
            "description": "Stale rate > 5%",
        },
        "high_flatline_rate": {
            "threshold": 10.0,  # % flatline
            "penalty": 10,
            "description": "Flatline rate > 10%",
        },
        "high_outlier_rate": {
            "threshold": 2.0,  # % outliers
            "penalty": 5,
            "description": "Outlier rate > 2%",
        },
    }

    def __init__(self):
        """Initialize station health scorer."""
        pass

    def score_station_health(
        self,
        station_id: str,
        window_days: int = 30,
        end_date: date = None,
    ) -> Dict[str, Any]:
        """Score station health over a rolling window.

        Args:
            station_id: Station identifier.
            window_days: Lookback window in days (default 30).
            end_date: End date for window (default today).

        Returns:
            Dict with:
            - station_id, window_days
            - availability_pct, missing_rate, duplicate_rate, stale_rate, flatline_rate, outlier_rate
            - health_score (0-100)
            - status ("healthy", "degraded", "offline")
            - computed_at (timestamp)
            - penalties_applied (list of applied penalties)
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=window_days)

        logger.info(
            f"Scoring station health for {station_id} "
            f"from {start_date} to {end_date} ({window_days} days)"
        )

        # Fetch metrics for station (in real implementation, would query data)
        metrics = self._calculate_station_metrics(
            station_id=station_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Calculate health score
        health_score, penalties_applied = self._calculate_health_score(metrics)

        # Classify status
        status = self._classify_status(health_score)

        result = {
            "station_id": station_id,
            "window_days": window_days,
            "availability_pct": metrics["availability_pct"],
            "missing_rate": metrics["missing_rate"],
            "duplicate_rate": metrics["duplicate_rate"],
            "stale_rate": metrics["stale_rate"],
            "flatline_rate": metrics["flatline_rate"],
            "outlier_rate": metrics["outlier_rate"],
            "health_score": health_score,
            "status": status,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "penalties_applied": penalties_applied,
        }

        logger.info(
            f"Station {station_id} health score: {health_score:.1f} ({status}). "
            f"Availability: {metrics['availability_pct']:.1f}%, "
            f"Duplicates: {metrics['duplicate_rate']:.1f}%, "
            f"Outliers: {metrics['outlier_rate']:.1f}%"
        )

        return result

    def score_batch(
        self,
        station_ids: List[str],
        window_days: int = 30,
        end_date: date = None,
    ) -> List[Dict[str, Any]]:
        """Score health for multiple stations.

        Args:
            station_ids: List of station identifiers.
            window_days: Lookback window in days.
            end_date: End date for window.

        Returns:
            List of health score dicts.
        """
        results = []
        for station_id in station_ids:
            result = self.score_station_health(
                station_id=station_id,
                window_days=window_days,
                end_date=end_date,
            )
            results.append(result)

        return results

    def _calculate_station_metrics(
        self,
        station_id: str,
        start_date: date,
        end_date: date,
    ) -> Dict[str, float]:
        """Calculate health metrics for station.

        Args:
            station_id: Station identifier.
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            Dict with availability_pct, missing_rate, duplicate_rate, etc.
        """
        # In real implementation, would query actual data from storage
        # For now, return placeholder metrics (tests will mock this)

        return {
            "availability_pct": 100.0,  # % of hours with data
            "missing_rate": 0.0,  # % of missing hourly records
            "duplicate_rate": 0.0,  # % of duplicate records
            "stale_rate": 0.0,  # % of stale observations
            "flatline_rate": 0.0,  # % of flatline values
            "outlier_rate": 0.0,  # % of extreme outliers
        }

    def _calculate_health_score(
        self, metrics: Dict[str, float]
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """Calculate health score from metrics.

        Args:
            metrics: Dict with availability_pct, missing_rate, etc.

        Returns:
            Tuple of (health_score, penalties_applied).
        """
        base_score = 100.0
        penalties_applied = []

        # Low availability penalty
        if metrics["availability_pct"] < self.PENALTIES["low_availability"]["threshold"]:
            penalty = self.PENALTIES["low_availability"]["penalty"]
            base_score -= penalty
            penalties_applied.append({
                "metric": "availability",
                "value": metrics["availability_pct"],
                "threshold": self.PENALTIES["low_availability"]["threshold"],
                "penalty": penalty,
                "description": self.PENALTIES["low_availability"]["description"],
            })

        # High missing rate penalty
        if metrics["missing_rate"] > self.PENALTIES["high_missing_rate"]["threshold"]:
            penalty = self.PENALTIES["high_missing_rate"]["penalty"]
            base_score -= penalty
            penalties_applied.append({
                "metric": "missing_rate",
                "value": metrics["missing_rate"],
                "threshold": self.PENALTIES["high_missing_rate"]["threshold"],
                "penalty": penalty,
                "description": self.PENALTIES["high_missing_rate"]["description"],
            })

        # High duplicate rate penalty
        if metrics["duplicate_rate"] > self.PENALTIES["high_duplicate_rate"]["threshold"]:
            penalty = self.PENALTIES["high_duplicate_rate"]["penalty"]
            base_score -= penalty
            penalties_applied.append({
                "metric": "duplicate_rate",
                "value": metrics["duplicate_rate"],
                "threshold": self.PENALTIES["high_duplicate_rate"]["threshold"],
                "penalty": penalty,
                "description": self.PENALTIES["high_duplicate_rate"]["description"],
            })

        # High stale rate penalty
        if metrics["stale_rate"] > self.PENALTIES["high_stale_rate"]["threshold"]:
            penalty = self.PENALTIES["high_stale_rate"]["penalty"]
            base_score -= penalty
            penalties_applied.append({
                "metric": "stale_rate",
                "value": metrics["stale_rate"],
                "threshold": self.PENALTIES["high_stale_rate"]["threshold"],
                "penalty": penalty,
                "description": self.PENALTIES["high_stale_rate"]["description"],
            })

        # High flatline rate penalty
        if metrics["flatline_rate"] > self.PENALTIES["high_flatline_rate"]["threshold"]:
            penalty = self.PENALTIES["high_flatline_rate"]["penalty"]
            base_score -= penalty
            penalties_applied.append({
                "metric": "flatline_rate",
                "value": metrics["flatline_rate"],
                "threshold": self.PENALTIES["high_flatline_rate"]["threshold"],
                "penalty": penalty,
                "description": self.PENALTIES["high_flatline_rate"]["description"],
            })

        # High outlier rate penalty
        if metrics["outlier_rate"] > self.PENALTIES["high_outlier_rate"]["threshold"]:
            penalty = self.PENALTIES["high_outlier_rate"]["penalty"]
            base_score -= penalty
            penalties_applied.append({
                "metric": "outlier_rate",
                "value": metrics["outlier_rate"],
                "threshold": self.PENALTIES["high_outlier_rate"]["threshold"],
                "penalty": penalty,
                "description": self.PENALTIES["high_outlier_rate"]["description"],
            })

        # Clamp to [0, 100]
        health_score = max(0.0, min(100.0, base_score))

        return health_score, penalties_applied

    @staticmethod
    def _classify_status(health_score: float) -> str:
        """Classify station status from health score.

        Args:
            health_score: Health score (0-100).

        Returns:
            Status string: "healthy", "degraded", or "offline".
        """
        if health_score >= 80:
            return HealthStatus.HEALTHY.value
        elif health_score >= 50:
            return HealthStatus.DEGRADED.value
        else:
            return HealthStatus.OFFLINE.value

    def get_health_summary(
        self,
        health_scores: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Get summary statistics from health scores.

        Args:
            health_scores: List of health score dicts.

        Returns:
            Dict with summary metrics.
        """
        if not health_scores:
            return {
                "total_stations": 0,
                "healthy": 0,
                "degraded": 0,
                "offline": 0,
                "mean_health_score": None,
                "median_health_score": None,
            }

        scores = [h["health_score"] for h in health_scores]
        statuses = [h["status"] for h in health_scores]

        healthy_count = statuses.count(HealthStatus.HEALTHY.value)
        degraded_count = statuses.count(HealthStatus.DEGRADED.value)
        offline_count = statuses.count(HealthStatus.OFFLINE.value)

        mean_score = sum(scores) / len(scores) if scores else None
        sorted_scores = sorted(scores)
        median_score = (
            sorted_scores[len(sorted_scores) // 2]
            if sorted_scores
            else None
        )

        return {
            "total_stations": len(health_scores),
            "healthy": healthy_count,
            "degraded": degraded_count,
            "offline": offline_count,
            "healthy_pct": (healthy_count / len(health_scores) * 100) if health_scores else 0,
            "mean_health_score": mean_score,
            "median_health_score": median_score,
        }
