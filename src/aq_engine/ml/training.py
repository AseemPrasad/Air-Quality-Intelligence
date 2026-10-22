"""ML model training pipeline."""

import importlib.metadata
import json
import logging
import pickle
import sys
from datetime import datetime, timezone
from typing import Dict, Tuple, Any, Optional
import numpy as np
from pathlib import Path

import polars as pl
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error

from aq_engine.ml.features import TARGET_PREFIX, target_column

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Train PM2.5 forecasting models."""

    VALID_MODELS = ["linear", "rf", "hgb", "xgboost"]
    MODELS_DIR = Path("models")

    # Columns with these prefixes are model inputs (label columns excluded).
    FEATURE_PREFIXES = (
        "pm25_",
        "temp_",
        "humidity_",
        "wind_",
        "hour_",
        "day_",
        "month_",
        "season_",
        "is_",
    )

    def __init__(self):
        """Initialize trainer."""
        self.MODELS_DIR.mkdir(exist_ok=True)

    def train_model(
        self,
        target_horizon: int,
        train_df: pl.DataFrame,
        val_df: pl.DataFrame,
        model_type: str = "linear",
        target_col: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """Train and evaluate PM2.5 model.

        Args:
            target_horizon: Prediction horizon in minutes
            train_df: Training DataFrame (features + label columns)
            val_df: Validation DataFrame
            model_type: "linear", "rf", "hgb"
            target_col: Label column. Defaults to target_column(target_horizon),
                which FeatureEngineer.generate_targets() fills in.

        Returns:
            Tuple of (trained_model_dict, metrics_dict)
        """
        if model_type not in self.VALID_MODELS:
            raise ValueError(f"model_type must be in {self.VALID_MODELS}")

        if target_col is None:
            target_col = target_column(target_horizon)

        # A lag or rolling column describes the past, so a model trained on it
        # never learns the horizon it is later used for.
        if not target_col.startswith(TARGET_PREFIX) and target_col.startswith(
            self.FEATURE_PREFIXES
        ):
            raise ValueError(
                f"target_col '{target_col}' is an input feature, not a future value. "
                f"Add labels with FeatureEngineer.generate_targets() and train on "
                f"'{target_column(target_horizon)}'."
            )

        for name, df in (("train_df", train_df), ("val_df", val_df)):
            if target_col not in df.columns:
                raise ValueError(
                    f"{name} has no '{target_col}' column. "
                    f"Add labels with FeatureEngineer.generate_targets()."
                )

        logger.info(
            f"Training {model_type} model (horizon={target_horizon}min) "
            f"on {len(train_df)} samples"
        )

        # Prepare data. Label columns for every horizon are left out, so a
        # 3h model cannot read the 1h label as an input.
        feature_cols = [
            col
            for col in train_df.columns
            if col.startswith(self.FEATURE_PREFIXES)
            and not col.startswith(TARGET_PREFIX)
        ]

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
        """Save trained model to disk with a JSON metadata sidecar.

        Writes two files:
        - ``{version}.pkl``: pickled model dict (unchanged serialization format).
        - ``{version}_metadata.json``: human-readable artifact metadata recording the
          Python version, scikit-learn version, model class, and artifact format
          identifier so that compatibility can be checked before loading.

        Args:
            model_dict: Trained model dict (as returned by :meth:`train_model`).
            version: Version string (e.g., ``"2026-08-15_linear"``).
            output_dir: Output directory.

        Returns:
            Path to saved model pickle file.
        """
        output_path = Path(output_dir) / f"{version}.pkl"
        with open(output_path, "wb") as f:
            pickle.dump(model_dict, f)

        # Resolve sklearn version safely — falls back to "unknown" if not installed
        try:
            sklearn_version = importlib.metadata.version("scikit-learn")
        except importlib.metadata.PackageNotFoundError:
            sklearn_version = "unknown"

        metadata = {
            "artifact_format_version": "1",
            "model_version": version,
            "model_type": model_dict.get("model_type"),
            "model_class": type(model_dict.get("model")).__name__,
            "target_horizon": model_dict.get("target_horizon"),
            "created_at": model_dict.get("created_at"),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "python_version": sys.version,
            "sklearn_version": sklearn_version,
            "feature_cols": model_dict.get("feature_cols", []),
        }

        metadata_path = Path(output_dir) / f"{version}_metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Model saved to {output_path}")
        logger.info(f"Model metadata saved to {metadata_path}")
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
