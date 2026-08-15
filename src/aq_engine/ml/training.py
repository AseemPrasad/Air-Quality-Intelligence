"""ML model training pipeline."""

import logging
import pickle
from datetime import datetime, timezone
from typing import Dict, Tuple, Any, Optional
import numpy as np
from pathlib import Path

import polars as pl
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Train PM2.5 forecasting models."""

    VALID_MODELS = ["linear", "rf", "hgb", "xgboost"]
    MODELS_DIR = Path("models")

    def __init__(self):
        """Initialize trainer."""
        self.MODELS_DIR.mkdir(exist_ok=True)

    def train_model(
        self,
        target_horizon: int,
        train_df: pl.DataFrame,
        val_df: pl.DataFrame,
        model_type: str = "linear",
        target_col: str = "pm25_lag_1h",
    ) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """Train and evaluate PM2.5 model.

        Args:
            target_horizon: Prediction horizon in minutes
            train_df: Training DataFrame (features)
            val_df: Validation DataFrame
            model_type: "linear", "rf", "hgb"
            target_col: Target column name

        Returns:
            Tuple of (trained_model_dict, metrics_dict)
        """
        if model_type not in self.VALID_MODELS:
            raise ValueError(f"model_type must be in {self.VALID_MODELS}")

        logger.info(
            f"Training {model_type} model (horizon={target_horizon}min) "
            f"on {len(train_df)} samples"
        )

        # Prepare data
        feature_cols = [col for col in train_df.columns if col.startswith(("pm25_", "temp_", "humidity_", "wind_", "hour_", "day_", "month_", "season_", "is_"))]
        
        X_train = train_df.select(feature_cols).to_numpy()
        y_train = train_df[target_col].to_numpy()
        
        X_val = val_df.select(feature_cols).to_numpy()
        y_val = val_df[target_col].to_numpy()

        # Remove NaN rows
        valid_train = ~(np.isnan(X_train).any(axis=1) | np.isnan(y_train))
        X_train = X_train[valid_train]
        y_train = y_train[valid_train]

        valid_val = ~(np.isnan(X_val).any(axis=1) | np.isnan(y_val))
        X_val = X_val[valid_val]
        y_val = y_val[valid_val]

        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_val_scaled = scaler.transform(X_val)

        # Train model
        if model_type == "linear":
            model = LinearRegression()
        elif model_type == "rf":
            model = RandomForestRegressor(n_estimators=100, max_depth=15, n_jobs=-1, random_state=42)
        elif model_type == "hgb":
            model = HistGradientBoostingRegressor(random_state=42, max_depth=10)
        else:
            raise ValueError(f"Unknown model type: {model_type}")

        model.fit(X_train_scaled, y_train)

        # Evaluate
        y_pred = model.predict(X_val_scaled)
        
        mae = mean_absolute_error(y_val, y_pred)
        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        median_ae = np.median(np.abs(y_val - y_pred))

        metrics = {
            "mae": float(mae),
            "rmse": float(rmse),
            "median_ae": float(median_ae),
            "n_train": len(X_train),
            "n_val": len(X_val),
        }

        # Feature importance
        if hasattr(model, "feature_importances_"):
            feature_importance = dict(zip(feature_cols, model.feature_importances_))
        else:
            feature_importance = {}

        model_dict = {
            "model": model,
            "scaler": scaler,
            "feature_cols": feature_cols,
            "model_type": model_type,
            "target_horizon": target_horizon,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "feature_importance": feature_importance,
        }

        logger.info(f"Model trained: MAE={mae:.2f}, RMSE={rmse:.2f}")

        return model_dict, metrics

    @staticmethod
    def save_model(model_dict: Dict, version: str, output_dir: str = "models") -> str:
        """Save trained model to disk.

        Args:
            model_dict: Trained model dict
            version: Version string (e.g., "2026-08-15_linear")
            output_dir: Output directory

        Returns:
            Path to saved model
        """
        output_path = Path(output_dir) / f"{version}.pkl"
        with open(output_path, "wb") as f:
            pickle.dump(model_dict, f)
        logger.info(f"Model saved to {output_path}")
        return str(output_path)

    @staticmethod
    def load_model(model_path: str) -> Dict:
        """Load trained model from disk.

        Args:
            model_path: Path to model file

        Returns:
            Model dict
        """
        with open(model_path, "rb") as f:
            model_dict = pickle.load(f)
        logger.info(f"Model loaded from {model_path}")
        return model_dict
