"""Baseline forecasting models for PM2.5 prediction.

Simple heuristic-based forecasts that serve as minimum performance benchmarks.
ML models must outperform these baselines to be production-ready.
"""

import logging
import statistics
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class BaselineForecaster:
    """Non-ML baseline forecasting models for PM2.5.

    Provides three simple heuristic forecasts:
    1. Naive: Current value = value at (target_time - horizon)
    2. Same-hour yesterday: Value at (target_time - 24h)
    3. Rolling mean: Mean of last 7 days at target hour

    These serve as minimum performance bar for ML models.

    Example:
        >>> forecaster = BaselineForecaster()
        >>>
        >>> # Naive forecast
        >>> forecast = forecaster.naive_current_value(
        ...     location_id="kolkata",
        ...     target_time=datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc),
        ...     horizon_minutes=60,
        ...     hourly_pm25_values={...}
        ... )
        >>> print(f"Prediction: {forecast['predicted_pm25']} ± {forecast['confidence']}")
    """

    # Confidence levels based on data availability and recency
    CONFIDENCE_HIGH = "high"      # Recent, complete data
    CONFIDENCE_MEDIUM = "medium"  # Some missing data or moderate lag
    CONFIDENCE_LOW = "low"        # Sparse or stale data

    # Rolling window size for rolling mean (days)
    ROLLING_WINDOW_DAYS = 7

    def __init__(self):
        """Initialize baseline forecaster."""
        pass

    def naive_current_value(
        self,
        location_id: str,
        target_time: datetime,
        horizon_minutes: int,
        hourly_pm25_values: Dict[str, Optional[float]],
    ) -> Dict[str, Any]:
        """Naive forecast: predict target_time value = value at (target_time - horizon).

        Simple persistence model: assumes PM2.5 will remain constant over horizon.

        Args:
            location_id: Location identifier
            target_time: Time to predict at (UTC)
            horizon_minutes: Prediction horizon in minutes
            hourly_pm25_values: Dict mapping hour timestamps (ISO 8601) → PM2.5 values

        Returns:
            Dict with predicted_pm25, baseline_type, confidence
        """
        target_time = ensure_utc(target_time)
        reference_time = target_time - timedelta(minutes=horizon_minutes)

        # Look up PM2.5 value at reference_time
        ref_time_key = reference_time.isoformat()
        predicted_value = hourly_pm25_values.get(ref_time_key)

        # Determine confidence based on data availability
        if predicted_value is not None:
            confidence = self.CONFIDENCE_HIGH
        else:
            confidence = self.CONFIDENCE_LOW
            predicted_value = None

        logger.debug(
            f"Naive forecast for {location_id} at {target_time} "
            f"(horizon={horizon_minutes}min): {predicted_value}"
        )

        return {
            "predicted_pm25": predicted_value,
            "baseline_type": "naive_current_value",
            "confidence": confidence,
            "reference_time": ref_time_key,
        }

    def same_hour_yesterday(
        self,
        location_id: str,
        target_time: datetime,
        hourly_pm25_values: Dict[str, Optional[float]],
    ) -> Dict[str, Any]:
        """Forecast using same hour yesterday: predict using (target_time - 24h) observation.

        Captures daily periodicity in PM2.5.

        Args:
            location_id: Location identifier
            target_time: Time to predict at (UTC)
            hourly_pm25_values: Dict mapping hour timestamps (ISO 8601) → PM2.5 values

        Returns:
            Dict with predicted_pm25, baseline_type, confidence
        """
        target_time = ensure_utc(target_time)
        yesterday_time = target_time - timedelta(hours=24)

        # Look up PM2.5 value at same hour yesterday
        yesterday_key = yesterday_time.isoformat()
        predicted_value = hourly_pm25_values.get(yesterday_key)

        # Determine confidence
        if predicted_value is not None:
            confidence = self.CONFIDENCE_HIGH
        else:
            confidence = self.CONFIDENCE_LOW
            predicted_value = None

        logger.debug(
            f"Same-hour-yesterday forecast for {location_id} at {target_time}: "
            f"{predicted_value}"
        )

        return {
            "predicted_pm25": predicted_value,
            "baseline_type": "same_hour_yesterday",
            "confidence": confidence,
            "reference_time": yesterday_key,
        }

    def rolling_mean_forecast(
        self,
        location_id: str,
        target_time: datetime,
        hourly_pm25_values: Dict[str, Optional[float]],
        window_days: int = ROLLING_WINDOW_DAYS,
    ) -> Dict[str, Any]:
        """Forecast using rolling mean: mean of last N days at target hour.

        Captures typical PM2.5 at this hour, smoothed over recent days.

        Args:
            location_id: Location identifier
            target_time: Time to predict at (UTC)
            hourly_pm25_values: Dict mapping hour timestamps (ISO 8601) → PM2.5 values
            window_days: Rolling window size in days (default 7)

        Returns:
            Dict with predicted_pm25, baseline_type, confidence
        """
        target_time = ensure_utc(target_time)

        # Collect values at same hour for last N days
        values = []
        for day_offset in range(window_days):
            sample_time = target_time - timedelta(days=day_offset + 1)
            sample_key = sample_time.isoformat()
            value = hourly_pm25_values.get(sample_key)

            if value is not None:
                values.append(value)

        # Calculate mean
        if values:
            predicted_value = statistics.mean(values)
            # Confidence based on data completeness
            completeness = len(values) / window_days
            if completeness >= 0.9:
                confidence = self.CONFIDENCE_HIGH
            elif completeness >= 0.7:
                confidence = self.CONFIDENCE_MEDIUM
            else:
                confidence = self.CONFIDENCE_LOW
        else:
            predicted_value = None
            confidence = self.CONFIDENCE_LOW

        logger.debug(
            f"Rolling mean forecast for {location_id} at {target_time} "
            f"({window_days}d window, {len(values)}/{window_days} values): "
            f"{predicted_value}"
        )

        return {
            "predicted_pm25": predicted_value,
            "baseline_type": f"rolling_mean_{window_days}d",
            "confidence": confidence,
            "values_used": len(values),
            "window_days": window_days,
        }

    def evaluate_baseline(
        self,
        predictions: List[Dict[str, Optional[float]]],
        actuals: List[float],
    ) -> Dict[str, Optional[float]]:
        """Evaluate baseline forecast performance.

        Computes MAE and RMSE against actual observations.

        Args:
            predictions: List of predicted values (may contain None)
            actuals: List of actual observed values

        Returns:
            Dict with mae, rmse metrics (None if insufficient valid predictions)
        """
        if len(predictions) != len(actuals):
            raise ValueError(
                f"predictions and actuals must have same length: "
                f"{len(predictions)} vs {len(actuals)}"
            )

        # Filter to valid predictions
        valid_pairs = [
            (pred, actual)
            for pred, actual in zip(predictions, actuals)
            if pred is not None and actual is not None
        ]

        if not valid_pairs:
            logger.warning("No valid predictions for baseline evaluation")
            return {"mae": None, "rmse": None, "valid_count": 0}

        # Calculate MAE and RMSE
        errors = [abs(pred - actual) for pred, actual in valid_pairs]
        squared_errors = [(pred - actual) ** 2 for pred, actual in valid_pairs]

        mae = statistics.mean(errors)
        rmse = (statistics.mean(squared_errors)) ** 0.5

        logger.info(
            f"Baseline evaluation: MAE={mae:.2f}, RMSE={rmse:.2f} "
            f"({len(valid_pairs)} valid predictions)"
        )

        return {
            "mae": mae,
            "rmse": rmse,
            "valid_count": len(valid_pairs),
        }

    @staticmethod
    def compare_baselines(
        baseline_results: Dict[str, Dict[str, float]],
    ) -> Tuple[str, float]:
        """Find best performing baseline.

        Args:
            baseline_results: Dict mapping baseline_type → metrics dict (with 'mae')

        Returns:
            Tuple of (best_baseline_type, best_mae)
        """
        valid_results = {
            btype: metrics
            for btype, metrics in baseline_results.items()
            if metrics.get("mae") is not None
        }

        if not valid_results:
            return None, float("inf")

        best_type = min(valid_results, key=lambda b: valid_results[b]["mae"])
        best_mae = valid_results[best_type]["mae"]

        logger.info(f"Best baseline: {best_type} (MAE={best_mae:.2f})")

        return best_type, best_mae

    @staticmethod
    def improvement_threshold(best_baseline_mae: float, min_improvement_pct: float = 5.0) -> float:
        """Calculate minimum performance threshold for ML models.

        ML model must beat best baseline by >= min_improvement_pct.

        Args:
            best_baseline_mae: Best baseline MAE
            min_improvement_pct: Minimum improvement required (default 5%)

        Returns:
            Maximum MAE for ML model to be considered production-ready
        """
        if best_baseline_mae is None or best_baseline_mae <= 0:
            return float("inf")

        threshold_mae = best_baseline_mae * (1 - min_improvement_pct / 100)
        logger.info(
            f"ML model must achieve MAE ≤ {threshold_mae:.2f} "
            f"(best baseline: {best_baseline_mae:.2f}, "
            f"improvement: {min_improvement_pct}%)"
        )

        return threshold_mae
