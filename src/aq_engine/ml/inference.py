"""Inference engine for multi-horizon PM2.5 predictions."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

from aq_engine.common import ensure_utc
from aq_engine.ml.features import FeatureEngineer
from aq_engine.ml.training import ModelTrainer
from aq_engine.ml.baselines import BaselineForecaster

logger = logging.getLogger(__name__)


class PredictionEngine:
    """Generate multi-horizon PM2.5 predictions with intervals."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        residuals: Optional[np.ndarray] = None,
    ):
        """Initialize prediction engine.

        Args:
            model_path: Path to trained model pickle file
            residuals: Validation residuals for interval estimation
        """
        self.model_path = model_path
        self.model_dict = None
        self.residuals = residuals
        self.feature_engineer = FeatureEngineer()
        self.baseline_forecaster = BaselineForecaster()

        if model_path:
            try:
                self.model_dict = ModelTrainer.load_model(model_path)
                logger.info(f"Loaded model from {model_path}")
            except Exception as e:
                logger.warning(f"Failed to load model: {e}")

    def predict_horizons(
        self,
        location_id: str,
        reference_time: datetime,
        horizons: List[int] = [60, 180, 360],
        hourly_pm25_values: Optional[Dict] = None,
        weather_facts: Optional[Dict] = None,
        citywide_baselines: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """Generate predictions for multiple horizons.

        Args:
            location_id: Location identifier
            reference_time: Reference time for feature computation (UTC)
            horizons: Prediction horizons in minutes
            hourly_pm25_values: PM2.5 historical values dict
            weather_facts: Weather data dict
            citywide_baselines: City-wide baselines for imputation

        Returns:
            List of prediction dicts (one per horizon)
        """
        reference_time = ensure_utc(reference_time)
        logger.info(
            f"Generating {len(horizons)} horizon predictions for {location_id} "
            f"at {reference_time}"
        )

        predictions = []

        for horizon_minutes in horizons:
            target_time = reference_time + timedelta(minutes=horizon_minutes)

            try:
                # Generate features (no future leakage)
                features = self.feature_engineer.generate_features(
                    target_time=reference_time,  # Use reference_time, not target_time
                    location_id=location_id,
                    horizon_minutes=horizon_minutes,
                    hourly_facts=hourly_pm25_values or {},
                    weather_facts=weather_facts or {},
                    citywide_pm25_baseline=citywide_baselines,
                )

                # Make prediction
                if self.model_dict is not None:
                    pred_dict = self._predict_with_model(
                        location_id, target_time, horizon_minutes, features
                    )
                else:
                    logger.warning("No model available, using baseline forecast")
                    pred_dict = self._predict_with_baseline(
                        location_id, target_time, features
                    )

                predictions.append(pred_dict)

            except Exception as e:
                logger.error(
                    f"Prediction failed for {location_id} horizon {horizon_minutes}: {e}"
                )
                # Fallback to baseline
                try:
                    pred_dict = self._predict_with_baseline(
                        location_id, target_time, features
                    )
                    predictions.append(pred_dict)
                except Exception as e2:
                    logger.error(f"Baseline forecast also failed: {e2}")
                    predictions.append({
                        "prediction_id": str(uuid.uuid4()),
                        "location_id": location_id,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "target_time": target_time.isoformat(),
                        "horizon_minutes": horizon_minutes,
                        "predicted_pm25": None,
                        "lower_bound": None,
                        "upper_bound": None,
                        "confidence": None,
                        "error_reason": "No prediction available",
                    })

        return predictions

    def _predict_with_model(
        self,
        location_id: str,
        target_time: datetime,
        horizon_minutes: int,
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make prediction using trained model.

        Args:
            location_id: Location identifier
            target_time: Target time for prediction
            horizon_minutes: Prediction horizon
            features: Generated feature dict

        Returns:
            Prediction dict
        """
        if self.model_dict is None:
            raise ValueError("No model loaded")

        model = self.model_dict["model"]
        scaler = self.model_dict["scaler"]
        feature_cols = self.model_dict["feature_cols"]

        # Extract feature values in correct order
        X = np.array([features.get(col) for col in feature_cols]).reshape(1, -1)

        # Check for missing features
        if np.isnan(X).any():
            raise ValueError("Missing features after imputation")

        # Scale and predict
        X_scaled = scaler.transform(X)
        predicted_pm25 = float(model.predict(X_scaled)[0])

        # Compute prediction interval
        lower_bound, upper_bound, confidence = self._compute_interval(predicted_pm25)

        return {
            "prediction_id": str(uuid.uuid4()),
            "model_version_id": hash(str(self.model_dict.get("created_at"))) % (10**9),
            "location_id": location_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_time": target_time.isoformat(),
            "horizon_minutes": horizon_minutes,
            "predicted_pm25": predicted_pm25,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "confidence": confidence,
            "model_type": self.model_dict.get("model_type"),
        }

    def _predict_with_baseline(
        self,
        location_id: str,
        target_time: datetime,
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make prediction using baseline forecast.

        Args:
            location_id: Location identifier
            target_time: Target time for prediction
            features: Generated feature dict

        Returns:
            Prediction dict
        """
        pm25_lag_1h = features.get("pm25_lag_1h")

        if pm25_lag_1h is None:
            raise ValueError("No PM2.5 lag feature available for baseline")

        return {
            "prediction_id": str(uuid.uuid4()),
            "location_id": location_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_time": target_time.isoformat(),
            "horizon_minutes": features.get("horizon_minutes"),
            "predicted_pm25": pm25_lag_1h,
            "lower_bound": pm25_lag_1h * 0.9,  # ±10% bounds
            "upper_bound": pm25_lag_1h * 1.1,
            "confidence": 0.5,  # Low confidence for baseline
            "model_type": "baseline",
            "note": "Using baseline fallback",
        }

    def _compute_interval(self, predicted_value: float) -> Tuple[float, float, float]:
        """Compute empirical prediction interval.

        Args:
            predicted_value: Point prediction

        Returns:
            Tuple of (lower_bound, upper_bound, confidence)
        """
        if self.residuals is None or len(self.residuals) < 10:
            # Default interval if no residuals available
            lower = predicted_value * 0.9
            upper = predicted_value * 1.1
            confidence = 0.5
        else:
            # Compute empirical percentiles
            lower_residual = np.percentile(self.residuals, 5)
            upper_residual = np.percentile(self.residuals, 95)

            lower = predicted_value + lower_residual
            upper = predicted_value + upper_residual

            # Confidence based on interval width
            interval_width = upper - lower
            # Normalize: width 10 → confidence 0.9, width 100 → confidence 0.1
            confidence = max(0.1, min(0.9, 1.0 - (interval_width / 100)))

        return float(lower), float(upper), float(confidence)

    @staticmethod
    def collect_residuals(
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> np.ndarray:
        """Collect residuals for interval estimation.

        Args:
            y_true: Actual values
            y_pred: Predicted values

        Returns:
            Residuals array
        """
        residuals = y_true - y_pred
        logger.info(
            f"Collected {len(residuals)} residuals "
            f"(mean={np.mean(residuals):.2f}, std={np.std(residuals):.2f})"
        )
        return residuals
