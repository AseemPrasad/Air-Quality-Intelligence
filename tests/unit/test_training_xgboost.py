"""Regression test for the advertised xgboost model type."""

import numpy as np
import polars as pl
import pytest

from aq_engine.ml.training import ModelTrainer


def test_xgboost_model_can_be_trained():
    pytest.importorskip("xgboost")

    n_rows = 40
    rng = np.random.default_rng(42)
    frame = pl.DataFrame(
        {
            "pm25_lag_1h": rng.uniform(20.0, 80.0, n_rows),
            "pm25_lag_2h": rng.uniform(20.0, 80.0, n_rows),
            "temp_lag_1h": rng.uniform(15.0, 35.0, n_rows),
            "target": rng.uniform(20.0, 80.0, n_rows),
        }
    )

    model_dict, metrics = ModelTrainer().train_model(
        target_horizon=60,
        train_df=frame,
        val_df=frame,
        model_type="xgboost",
        target_col="target",
    )

    assert model_dict["model_type"] == "xgboost"
    assert metrics["mae"] >= 0.0
    assert "pm25_lag_1h" in model_dict["feature_importance"]
