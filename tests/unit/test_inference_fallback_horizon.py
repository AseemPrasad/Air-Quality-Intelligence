"""Regression test for horizon isolation in prediction fallbacks."""

from datetime import datetime, timezone

from aq_engine.ml.inference import PredictionEngine


def test_failed_horizon_does_not_reuse_previous_features(monkeypatch):
    engine = PredictionEngine()
    target = datetime(2026, 8, 15, 10, tzinfo=timezone.utc)
    calls = {"count": 0}

    def fake_generate_features(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"pm25_lag_1h": 42.0, "horizon_minutes": 60}
        raise ValueError("feature generation failed")

    monkeypatch.setattr(
        engine.feature_engineer, "generate_features", fake_generate_features
    )

    predictions = engine.predict_horizons(
        location_id="kolkata",
        reference_time=target,
        horizons=[60, 180],
        hourly_pm25_values={},
    )

    assert predictions[0]["horizon_minutes"] == 60
    assert predictions[0]["predicted_pm25"] == 42.0
    assert predictions[1]["horizon_minutes"] == 180
    assert predictions[1]["predicted_pm25"] is None
    assert predictions[1]["error_reason"] == "No prediction available"
