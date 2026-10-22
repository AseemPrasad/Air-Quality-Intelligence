"""Regression tests for feature column selection during training."""

import numpy as np
import polars as pl

from aq_engine.ml.training import ModelTrainer


def test_trainer_keeps_pressure_and_calendar_features():
    n_rows = 20
    frame = pl.DataFrame(
        {
            "pm25_lag_1h": np.arange(n_rows, dtype=float),
            "pressure_lag_1h": np.linspace(1000.0, 1020.0, n_rows),
            "month": np.full(n_rows, 8),
            "season": np.full(n_rows, 2),
            "hour_since_midnight": np.full(n_rows, 10),
            "target": np.arange(n_rows, dtype=float),
        }
    )

    model_dict, _ = ModelTrainer().train_model(
        target_horizon=60,
        train_df=frame,
        val_df=frame,
        model_type="linear",
        target_col="target",
    )

    assert "pressure_lag_1h" in model_dict["feature_cols"]
    assert "month" in model_dict["feature_cols"]
    assert "season" in model_dict["feature_cols"]
    assert "hour_since_midnight" in model_dict["feature_cols"]
    assert "target" not in model_dict["feature_cols"]


def test_metadata_columns_are_not_treated_as_features():
    n_rows = 10
    frame = pl.DataFrame(
        {
            "pm25_lag_1h": np.arange(n_rows, dtype=float),
            "location_id": ["kolkata"] * n_rows,
            "target_time": ["2026-08-15T10:00:00Z"] * n_rows,
            "target": np.arange(n_rows, dtype=float),
        }
    )

    model_dict, _ = ModelTrainer().train_model(
        target_horizon=60,
        train_df=frame,
        val_df=frame,
        model_type="linear",
        target_col="target",
    )

    assert model_dict["feature_cols"] == ["pm25_lag_1h"]
