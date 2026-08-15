"""Tests for ML model training and evaluation."""

import pytest
import numpy as np
import polars as pl
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from aq_engine.ml.training import ModelTrainer
from aq_engine.ml.evaluation import ModelEvaluator


@pytest.fixture
def trainer():
    """ModelTrainer instance."""
    return ModelTrainer()


@pytest.fixture
def evaluator():
    """ModelEvaluator instance."""
    return ModelEvaluator()


@pytest.fixture
def sample_data():
    """Create sample training data."""
    np.random.seed(42)
    n_samples = 100

    train_data = pl.DataFrame({
        "pm25_lag_1h": np.random.uniform(40, 80, n_samples),
        "pm25_lag_2h": np.random.uniform(40, 80, n_samples),
        "pm25_lag_6h": np.random.uniform(40, 80, n_samples),
        "temp_lag_1h": np.random.uniform(15, 35, n_samples),
        "humidity_lag_1h": np.random.uniform(40, 90, n_samples),
        "wind_speed_lag_1h": np.random.uniform(0, 10, n_samples),
        "hour_of_day": np.random.randint(0, 24, n_samples),
        "day_of_week": np.random.randint(0, 7, n_samples),
        "season": np.random.randint(0, 4, n_samples),
    })

    val_data = pl.DataFrame({
        "pm25_lag_1h": np.random.uniform(40, 80, 50),
        "pm25_lag_2h": np.random.uniform(40, 80, 50),
        "pm25_lag_6h": np.random.uniform(40, 80, 50),
        "temp_lag_1h": np.random.uniform(15, 35, 50),
        "humidity_lag_1h": np.random.uniform(40, 90, 50),
        "wind_speed_lag_1h": np.random.uniform(0, 10, 50),
        "hour_of_day": np.random.randint(0, 24, 50),
        "day_of_week": np.random.randint(0, 7, 50),
        "season": np.random.randint(0, 4, 50),
    })

    return train_data, val_data


class TestModelTrainer:
    """Test model training."""

    def test_train_linear_model(self, trainer, sample_data):
        """Test training linear regression model."""
        train_df, val_df = sample_data
        model_dict, metrics = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="linear",
        )

        assert "model" in model_dict
        assert "mae" in metrics
        assert "rmse" in metrics
        assert metrics["mae"] > 0
        assert metrics["rmse"] > 0

    def test_train_random_forest_model(self, trainer, sample_data):
        """Test training random forest model."""
        train_df, val_df = sample_data
        model_dict, metrics = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="rf",
        )

        assert model_dict["model_type"] == "rf"
        assert metrics["mae"] > 0

    def test_train_hgb_model(self, trainer, sample_data):
        """Test training HistGradientBoosting model."""
        train_df, val_df = sample_data
        model_dict, metrics = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="hgb",
        )

        assert model_dict["model_type"] == "hgb"
        assert metrics["mae"] > 0

    def test_invalid_model_type(self, trainer, sample_data):
        """Test invalid model type raises error."""
        train_df, val_df = sample_data
        with pytest.raises(ValueError):
            trainer.train_model(
                target_horizon=60,
                train_df=train_df,
                val_df=val_df,
                model_type="invalid",
            )

    def test_model_save_load(self, trainer, sample_data):
        """Test model save and load roundtrip."""
        train_df, val_df = sample_data
        model_dict, _ = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="linear",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # Save
            path = trainer.save_model(model_dict, "test_model", tmpdir)
            assert Path(path).exists()

            # Load
            loaded = trainer.load_model(path)
            assert loaded["model_type"] == "linear"
            assert loaded["target_horizon"] == 60


class TestModelEvaluator:
    """Test model evaluation."""

    def test_evaluate_metrics(self, evaluator):
        """Test metric calculation."""
        predictions = np.array([50.0, 52.0, 48.0, 55.0])
        actuals = np.array([51.0, 50.0, 50.0, 52.0])

        metrics = evaluator.evaluate(predictions, actuals)

        assert metrics["mae"] == pytest.approx(2.0, abs=0.01)
        assert metrics["n_samples"] == 4

    def test_evaluate_with_nan(self, evaluator):
        """Test evaluation handles NaN values."""
        predictions = np.array([50.0, np.nan, 48.0, 55.0])
        actuals = np.array([51.0, 50.0, 50.0, 52.0])

        metrics = evaluator.evaluate(predictions, actuals)

        assert metrics["n_samples"] == 3

    def test_compare_models(self, evaluator):
        """Test model comparison."""
        scores = {
            "linear": {"mae": 3.5},
            "rf": {"mae": 2.8},
            "hgb": {"mae": 2.5},
        }

        ranked = evaluator.compare_models(scores)

        assert ranked[0][0] == "hgb"
        assert ranked[0][1] == 2.5

    def test_promotion_criteria_pass(self, evaluator):
        """Test promotion when improvement meets threshold."""
        should_promote = evaluator.check_promotion_criteria(
            candidate_mae=2.5,
            current_mae=3.0,
            min_improvement_pct=5.0,
        )

        # (3.0 - 2.5) / 3.0 * 100 = 16.67% > 5%
        assert should_promote is True

    def test_promotion_criteria_fail(self, evaluator):
        """Test rejection when improvement below threshold."""
        should_promote = evaluator.check_promotion_criteria(
            candidate_mae=2.95,
            current_mae=3.0,
            min_improvement_pct=5.0,
        )

        # (3.0 - 2.95) / 3.0 * 100 = 1.67% < 5%
        assert should_promote is False

    def test_promotion_no_current_model(self, evaluator):
        """Test promotion when no current model."""
        should_promote = evaluator.check_promotion_criteria(
            candidate_mae=2.5,
            current_mae=None,
        )

        assert should_promote is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
