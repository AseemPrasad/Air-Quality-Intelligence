"""Tests for inference engine."""

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta

from aq_engine.ml.inference import PredictionEngine


@pytest.fixture
def inference_engine():
    """PredictionEngine instance without model."""
    return PredictionEngine()


@pytest.fixture
def reference_time():
    """Reference time for predictions."""
    return datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def location_id():
    """Location identifier."""
    return "kolkata"


class TestSingleHorizon:
    """Test single horizon prediction."""

    def test_predict_single_horizon_baseline(
        self, inference_engine, location_id, reference_time
    ):
        """Test single horizon prediction with baseline."""
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=[60],
            hourly_pm25_values={},
            weather_facts={},
        )

        assert len(predictions) == 1
        pred = predictions[0]
        assert "prediction_id" in pred
        assert pred["location_id"] == location_id
        assert pred["horizon_minutes"] == 60

    def test_prediction_has_required_fields(
        self, inference_engine, location_id, reference_time
    ):
        """Test prediction has all required fields."""
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=[60],
        )

        pred = predictions[0]
        required_fields = [
            "prediction_id",
            "location_id",
            "generated_at",
            "target_time",
            "horizon_minutes",
            "predicted_pm25",
            "lower_bound",
            "upper_bound",
            "confidence",
        ]

        for field in required_fields:
            assert field in pred


class TestMultiHorizon:
    """Test multi-horizon predictions."""

    def test_predict_multiple_horizons(
        self, inference_engine, location_id, reference_time
    ):
        """Test multiple horizon predictions."""
        horizons = [60, 180, 360]
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=horizons,
        )

        assert len(predictions) == 3

    def test_horizons_have_different_target_times(
        self, inference_engine, location_id, reference_time
    ):
        """Test each horizon has correct target_time."""
        horizons = [60, 180, 360]
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=horizons,
        )

        for i, pred in enumerate(predictions):
            target = datetime.fromisoformat(pred["target_time"])
            expected_target = reference_time + timedelta(minutes=horizons[i])
            assert target == expected_target


class TestPredictionInterval:
    """Test prediction interval computation."""

    def test_interval_without_residuals(self, inference_engine):
        """Test interval computation with default fallback."""
        lower, upper, confidence = inference_engine._compute_interval(50.0)

        assert lower < 50.0
        assert upper > 50.0
        assert 0.0 <= confidence <= 1.0

    def test_interval_with_residuals(self, inference_engine):
        """Test interval computation with residuals."""
        residuals = np.random.normal(0, 5, 100)
        engine = PredictionEngine(residuals=residuals)

        lower, upper, confidence = engine._compute_interval(50.0)

        assert lower < 50.0
        assert upper > 50.0
        assert 0.0 <= confidence <= 1.0


class TestErrorHandling:
    """Test error handling and fallbacks."""

    def test_prediction_without_model_uses_baseline(
        self, inference_engine, location_id, reference_time
    ):
        """Test fallback to baseline when model unavailable."""
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=[60],
        )

        pred = predictions[0]
        assert pred["predicted_pm25"] is not None or "error_reason" in pred

    def test_multiple_horizons_continue_on_error(
        self, inference_engine, location_id, reference_time
    ):
        """Test multi-horizon handles errors gracefully."""
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=[60, 180, 360],
            hourly_pm25_values={},
        )

        assert len(predictions) == 3


class TestPredictionMetadata:
    """Test prediction metadata."""

    def test_unique_prediction_ids(self, inference_engine, location_id, reference_time):
        """Test each prediction gets unique ID."""
        predictions = inference_engine.predict_horizons(
            location_id=location_id,
            reference_time=reference_time,
            horizons=[60, 180],
        )

        ids = [p["prediction_id"] for p in predictions]
        assert len(ids) == len(set(ids))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
