"""Tests for ML model training and evaluation."""

import importlib.metadata
import json
import sys

import numpy as np
import polars as pl
import pytest
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

    def test_target_column_is_not_used_as_a_feature(self, trainer, sample_data):
        """The value being predicted must not leak into the model inputs."""
        train_df, val_df = sample_data

        model_dict, _ = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="linear",
            target_col="pm25_lag_1h",
        )

        assert "pm25_lag_1h" not in model_dict["feature_cols"]
        assert "pm25_lag_2h" in model_dict["feature_cols"]

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


class TestModelArtifactMetadata:
    """Regression tests for save_model metadata sidecar.

    Prior to the fix, save_model() wrote only a pickle file with no record of
    the Python version, scikit-learn version, or artifact format.  Loading a
    pickle produced with a different sklearn version can silently produce wrong
    results or raise an error.

    These tests verify that a human-readable ``_metadata.json`` sidecar is
    written alongside the pickle so compatibility can be checked.
    """

    @pytest.fixture
    def trained_model(self, trainer, sample_data):
        """Return a freshly trained linear model dict."""
        train_df, val_df = sample_data
        model_dict, _ = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="linear",
        )
        return model_dict

    def test_metadata_sidecar_is_created(self, trainer, trained_model):
        """save_model() creates a _metadata.json alongside the .pkl."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            assert metadata_path.exists(), "metadata sidecar must be written"

    def test_metadata_is_valid_json(self, trainer, trained_model):
        """The metadata sidecar must be parseable JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert isinstance(metadata, dict)

    def test_metadata_artifact_format_version(self, trainer, trained_model):
        """Metadata must carry an artifact_format_version key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert metadata["artifact_format_version"] == "1"

    def test_metadata_records_python_version(self, trainer, trained_model):
        """Metadata must record the Python version used during save."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert "python_version" in metadata
            assert sys.version in metadata["python_version"]

    def test_metadata_records_sklearn_version(self, trainer, trained_model):
        """Metadata must record the scikit-learn version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert "sklearn_version" in metadata
            expected = importlib.metadata.version("scikit-learn")
            assert metadata["sklearn_version"] == expected

    def test_metadata_records_model_type(self, trainer, trained_model):
        """Metadata must record the model_type string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert metadata["model_type"] == "linear"

    def test_metadata_records_model_class(self, trainer, trained_model):
        """Metadata must record the concrete sklearn class name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "v1_linear", tmpdir)

            metadata_path = Path(tmpdir) / "v1_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert metadata["model_class"] == "LinearRegression"

    def test_metadata_model_class_for_rf(self, trainer, sample_data):
        """model_class must reflect the actual estimator (RandomForestRegressor)."""
        train_df, val_df = sample_data
        model_dict, _ = trainer.train_model(
            target_horizon=60,
            train_df=train_df,
            val_df=val_df,
            model_type="rf",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(model_dict, "v1_rf", tmpdir)

            metadata_path = Path(tmpdir) / "v1_rf_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert metadata["model_class"] == "RandomForestRegressor"
            assert metadata["model_type"] == "rf"

    def test_metadata_version_matches_argument(self, trainer, trained_model):
        """model_version in metadata must match the version argument."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trainer.save_model(trained_model, "2026-09-11_linear", tmpdir)

            metadata_path = Path(tmpdir) / "2026-09-11_linear_metadata.json"
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)

            assert metadata["model_version"] == "2026-09-11_linear"

    def test_existing_load_behavior_unchanged(self, trainer, trained_model):
        """load_model() must still return a usable model dict (backward compat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = trainer.save_model(trained_model, "v1_linear", tmpdir)
            loaded = trainer.load_model(path)

            assert loaded["model_type"] == "linear"
            assert loaded["target_horizon"] == 60
            assert "model" in loaded
            assert "scaler" in loaded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
