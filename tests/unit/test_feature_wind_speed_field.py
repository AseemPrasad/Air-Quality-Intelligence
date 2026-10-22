"""Regression tests for canonical wind speed field names."""

from datetime import datetime, timedelta, timezone

from aq_engine.ml.features import FeatureEngineer


def _weather_facts(target_time, field_name, values):
    facts = {}
    for offset, value in enumerate(values, start=1):
        hour = target_time - timedelta(hours=offset)
        facts[("kolkata", hour.isoformat())] = {
            "temperature_c": 28.0,
            "humidity_pct": 70.0,
            field_name: value,
            "pressure_hpa": 1010.0,
            "wind_direction_deg": 180.0,
        }
    return facts


def test_wind_speed_kmh_populates_lag_and_rolling_features():
    target = datetime(2026, 8, 15, 10, tzinfo=timezone.utc)
    facts = _weather_facts(target, "wind_speed_kmh", [12.0, 18.0])

    features = FeatureEngineer().generate_features(
        target_time=target,
        location_id="kolkata",
        horizon_minutes=60,
        hourly_facts={},
        weather_facts=facts,
    )

    assert features["wind_speed_lag_1h"] == 12.0
    assert features["wind_speed_rolling_mean_6h"] == 15.0


def test_legacy_wind_speed_ms_is_still_accepted():
    target = datetime(2026, 8, 15, 10, tzinfo=timezone.utc)
    facts = _weather_facts(target, "wind_speed_ms", [4.0])

    features, _ = FeatureEngineer()._extract_weather_lags(
        target, "kolkata", facts, None
    )

    assert features["wind_speed_lag_1h"] == 4.0
