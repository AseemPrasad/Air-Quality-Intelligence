"""Forecast labels must sit at reference_time + horizon, and each horizon gets its own model."""

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from aq_engine.ml.features import FeatureEngineer, target_column
from aq_engine.ml.inference import PredictionEngine
from aq_engine.ml.training import ModelTrainer

START = datetime(2026, 8, 1, tzinfo=timezone.utc)
HOURS = 24 * 21
HORIZONS = [60, 180, 360]


@pytest.fixture(scope="module")
def facts():
    """Three weeks of hourly PM2.5 with a daily cycle and some noise."""
    rng = np.random.default_rng(7)
    out = {}
    for i in range(HOURS):
        hour = START + timedelta(hours=i)
        value = 60 + 20 * math.sin(2 * math.pi * i / 24) + rng.normal(0, 3)
        out[("loc", "pm25", hour.isoformat())] = {"observed_value": float(value)}
    return out


@pytest.fixture(scope="module")
def frames(facts):
    """Feature + label rows, split in time order (first 80% train)."""
    engineer = FeatureEngineer()
    rows = []
    # Skip the first day so every lag exists, and stop 6h early so every label exists.
    for i in range(24, HOURS - 6):
        ref = START + timedelta(hours=i)
        row = engineer.generate_features(ref, "loc", 60, facts, {})
        row.update(engineer.generate_targets(ref, "loc", HORIZONS, facts))
        rows.append(
            {
                k: v
                for k, v in row.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        )
    df = pl.DataFrame(rows)
    split = int(len(df) * 0.8)
    return df[:split], df[split:]


@pytest.fixture
def trainer(tmp_path, monkeypatch):
    # ModelTrainer creates ./models on init; keep it out of the repo.
    monkeypatch.chdir(tmp_path)
    return ModelTrainer()


class TestGenerateTargets:
    """FeatureEngineer.generate_targets()"""

    @pytest.mark.parametrize("horizon", HORIZONS)
    def test_label_is_what_lag_1h_reads_one_horizon_later(self, facts, horizon):
        engineer = FeatureEngineer()
        ref = START + timedelta(hours=100)

        targets = engineer.generate_targets(ref, "loc", [horizon], facts)
        later = engineer.generate_features(
            ref + timedelta(minutes=horizon), "loc", 60, facts, {}
        )

        assert targets[target_column(horizon)] == later["pm25_lag_1h"]

    def test_labels_never_come_from_hours_the_features_read(self, facts):
        engineer = FeatureEngineer()
        ref = START + timedelta(hours=100)
        history_only = {
            key: fact
            for key, fact in facts.items()
            if datetime.fromisoformat(key[2]) < ref
        }

        targets = engineer.generate_targets(ref, "loc", HORIZONS, history_only)
        features = engineer.generate_features(ref, "loc", 60, history_only, {})

        assert all(value is None for value in targets.values())
        assert features["pm25_lag_1h"] is not None

    def test_missing_label_hour_is_left_empty(self, facts):
        engineer = FeatureEngineer()
        ref = START + timedelta(hours=100)
        gap = dict(facts)
        del gap[("loc", "pm25", ref.isoformat())]

        targets = engineer.generate_targets(ref, "loc", [60, 180], gap)

        assert targets[target_column(60)] is None
        assert targets[target_column(180)] is not None

    @pytest.mark.parametrize("horizon", [0, 30, 90])
    def test_rejects_horizons_that_are_not_whole_hours(self, facts, horizon):
        with pytest.raises(ValueError, match="whole number of hours"):
            FeatureEngineer().generate_targets(START, "loc", [horizon], facts)


class TestTrainerTargets:
    """ModelTrainer.train_model() label handling"""

    def test_defaults_to_the_label_for_its_horizon(self, trainer, frames):
        train_df, val_df = frames

        model_dict, metrics = trainer.train_model(360, train_df, val_df)

        assert model_dict["target_horizon"] == 360
        assert metrics["n_train"] > 0
        # The old default (pm25_lag_1h) could be rebuilt exactly from
        # rolling_mean_3h, lag_2h and lag_3h, which gave a near-zero error.
        assert metrics["mae"] > 1e-6

    def test_rejects_a_lag_feature_as_the_label(self, trainer, frames):
        train_df, val_df = frames

        with pytest.raises(ValueError, match="input feature"):
            trainer.train_model(60, train_df, val_df, target_col="pm25_lag_1h")

    def test_missing_label_column_is_an_error(self, trainer, frames):
        train_df, val_df = frames

        with pytest.raises(ValueError, match="generate_targets"):
            trainer.train_model(
                180,
                train_df.drop(target_column(180)),
                val_df.drop(target_column(180)),
            )

    def test_labels_for_other_horizons_are_not_features(self, trainer, frames):
        train_df, val_df = frames

        model_dict, _ = trainer.train_model(180, train_df, val_df)

        assert not [c for c in model_dict["feature_cols"] if c.startswith("pm25_target_")]
        assert "pm25_lag_1h" in model_dict["feature_cols"]

    def test_each_horizon_learns_its_own_model(self, trainer, frames):
        train_df, val_df = frames

        one_hour, _ = trainer.train_model(60, train_df, val_df)
        six_hours, _ = trainer.train_model(360, train_df, val_df)

        assert not np.allclose(one_hour["model"].coef_, six_hours["model"].coef_)


class TestPredictionHorizons:
    """PredictionEngine picks the model trained for each horizon."""

    @pytest.fixture
    def model_paths(self, trainer, frames, tmp_path):
        train_df, val_df = frames
        paths = {}
        for horizon in (60, 360):
            model_dict, _ = trainer.train_model(horizon, train_df, val_df)
            paths[horizon] = ModelTrainer.save_model(
                model_dict, f"linear_{horizon}", str(tmp_path)
            )
        return paths

    def test_single_model_only_answers_its_own_horizon(self, facts, model_paths):
        engine = PredictionEngine(model_path=model_paths[60])
        ref = START + timedelta(hours=HOURS - 12)

        predictions = engine.predict_horizons("loc", ref, HORIZONS, facts, {})

        assert [p["model_type"] for p in predictions] == ["linear", "baseline", "baseline"]

    def test_one_model_per_horizon_gives_different_forecasts(self, facts, model_paths):
        engine = PredictionEngine(model_paths=model_paths)
        ref = START + timedelta(hours=HOURS - 12)

        one_hour, six_hours = engine.predict_horizons("loc", ref, [60, 360], facts, {})

        assert one_hour["model_type"] == six_hours["model_type"] == "linear"
        assert one_hour["predicted_pm25"] != pytest.approx(six_hours["predicted_pm25"])
        assert one_hour["model_version_id"] != six_hours["model_version_id"]

    def test_model_registered_under_the_wrong_horizon_is_skipped(self, model_paths):
        engine = PredictionEngine(model_paths={360: model_paths[60]})

        assert engine.models == {}

    def test_failed_horizon_does_not_reuse_the_previous_features(self, facts):
        engine = PredictionEngine()
        ref = START + timedelta(hours=HOURS - 12)

        # A negative horizon makes feature generation raise for the second entry.
        predictions = engine.predict_horizons("loc", ref, [60, -60], facts, {})

        assert predictions[0]["model_type"] == "baseline"
        assert predictions[1]["horizon_minutes"] == -60
        assert predictions[1]["predicted_pm25"] is None
