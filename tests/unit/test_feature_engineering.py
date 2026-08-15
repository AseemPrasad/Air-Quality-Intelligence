"""Unit tests for feature engineering with future-leakage prevention.

Tests ensure all features use only observations strictly before target_time.
"""

import pytest
import math
from datetime import datetime, timezone, timedelta

from aq_engine.ml.features import FeatureEngineer


@pytest.fixture
def engineer():
    """FeatureEngineer instance."""
    return FeatureEngineer()


@pytest.fixture
def target_time():
    """Target time for features (2026-08-15 10:00 UTC)."""
    return datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def location_id():
    """Location identifier."""
    return "kolkata"


@pytest.fixture
def hourly_pm25_facts(target_time, location_id):
    """Sample hourly PM2.5 facts (before target_time only)."""
    facts = {}

    # Data from 1-24 hours before target_time
    for lag_hours in range(1, 25):
        hour_time = target_time - timedelta(hours=lag_hours)
        key = (location_id, "pm25", hour_time.isoformat())
        facts[key] = {
            "observed_value": 50.0 + lag_hours,  # Increasing values for testing
            "hour_start": hour_time.isoformat(),
        }

    return facts


@pytest.fixture
def hourly_weather_facts(target_time, location_id):
    """Sample hourly weather facts."""
    facts = {}

    for lag_hours in range(1, 25):
        hour_time = target_time - timedelta(hours=lag_hours)
        key = (location_id, hour_time.isoformat())
        facts[key] = {
            "temperature_c": 25.0 + lag_hours * 0.5,
            "humidity_pct": 60.0 + lag_hours * 0.2,
            "wind_speed_ms": 5.0 + lag_hours * 0.1,
            "pressure_hpa": 1013.0 - lag_hours * 0.1,
            "wind_direction_deg": 180.0 + lag_hours * 5,  # Varies for testing
            "hour_start": hour_time.isoformat(),
        }

    return facts


@pytest.fixture
def citywide_pm25_baseline():
    """City-wide PM2.5 baseline for fallback."""
    return {
        "historical_median": 55.0,
        "mad": 8.0,
        "p95": 75.0,
        "p99": 85.0,
    }


@pytest.fixture
def citywide_weather_baseline():
    """City-wide weather baseline for fallback."""
    return {
        "temperature_c_mean": 26.0,
        "humidity_pct_mean": 62.0,
        "wind_speed_ms_mean": 5.5,
        "pressure_hpa_mean": 1012.5,
        "wind_direction_deg_mean": 200.0,
    }


class TestFeatureGeneration:
    """Test basic feature generation."""

    def test_generate_features_returns_dict(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test generate_features returns dict with all fields."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert isinstance(features, dict)
        assert "location_id" in features
        assert "target_time" in features
        assert "horizon_minutes" in features
        assert features["location_id"] == location_id

    def test_feature_version_set(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test feature_version is set."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "feature_version" in features
        assert features["feature_version"] == "1.0.0"


class TestPM25Lags:
    """Test PM2.5 lag feature extraction."""

    def test_pm25_lag_1h_correct_value(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 lag 1h uses correct observation."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # At 1 hour before target_time, value should be 50.0 + 1 = 51.0
        assert features["pm25_lag_1h"] == 51.0

    def test_pm25_lag_6h_correct_value(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 lag 6h uses correct observation."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # At 6 hours before target_time, value should be 50.0 + 6 = 56.0
        assert features["pm25_lag_6h"] == 56.0

    def test_pm25_lag_24h_correct_value(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 lag 24h uses correct observation."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # At 24 hours before target_time, value should be 50.0 + 24 = 74.0
        assert features["pm25_lag_24h"] == 74.0

    def test_all_lag_features_present(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test all lag features are generated."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        for lag_hours in [1, 2, 3, 6, 12, 24]:
            assert f"pm25_lag_{lag_hours}h" in features


class TestPM25RollingStatistics:
    """Test PM2.5 rolling statistics."""

    def test_pm25_rolling_mean_3h(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 rolling mean 3h."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # Values at -1h, -2h, -3h: 51.0, 52.0, 53.0
        # Mean = (51 + 52 + 53) / 3 = 52.0
        expected_mean = (51.0 + 52.0 + 53.0) / 3
        assert pytest.approx(features["pm25_rolling_mean_3h"], abs=0.01) == expected_mean

    def test_pm25_rolling_mean_6h(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 rolling mean 6h."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # Values at -1h to -6h: 51-56
        # Mean = (51 + 52 + 53 + 54 + 55 + 56) / 6 = 53.5
        expected_mean = sum(range(51, 57)) / 6
        assert pytest.approx(features["pm25_rolling_mean_6h"], abs=0.01) == expected_mean

    def test_pm25_rolling_std_6h(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 rolling std 6h."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # Std dev should be non-zero for varying values
        assert features["pm25_rolling_std_6h"] > 0

    def test_pm25_rolling_max_24h(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test PM2.5 rolling max 24h."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        # Max of 1-24h before target: 74.0
        assert features["pm25_rolling_max_24h"] == 74.0


class TestWeatherFeatures:
    """Test weather feature extraction."""

    def test_temp_lag_1h_present(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test temperature lag 1h feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "temp_lag_1h" in features
        # Should be 25.0 + 1*0.5 = 25.5
        assert pytest.approx(features["temp_lag_1h"], abs=0.01) == 25.5

    def test_humidity_lag_1h_present(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test humidity lag 1h feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "humidity_lag_1h" in features

    def test_wind_speed_lag_1h_present(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test wind speed lag 1h feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "wind_speed_lag_1h" in features

    def test_pressure_lag_1h_present(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test pressure lag 1h feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "pressure_lag_1h" in features

    def test_weather_rolling_mean_6h(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test weather rolling statistics."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "temp_rolling_mean_6h" in features
        assert features["temp_rolling_mean_6h"] is not None


class TestWindDirectionTransform:
    """Test wind direction sin/cos transformation."""

    def test_wind_direction_sin_cos_generated(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test wind direction sin/cos features are generated."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "wind_dir_sin" in features
        assert "wind_dir_cos" in features

    def test_wind_direction_pythagorean_identity(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test sin²+cos² ≈ 1 (Pythagorean identity)."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        sin_val = features["wind_dir_sin"]
        cos_val = features["wind_dir_cos"]

        if sin_val is not None and cos_val is not None:
            pythag_sum = sin_val**2 + cos_val**2
            assert pytest.approx(pythag_sum, abs=0.001) == 1.0

    def test_wind_direction_0_deg(self, engineer):
        """Test wind direction 0° (North)."""
        sin_val, cos_val = engineer._transform_wind_direction(0.0)

        assert pytest.approx(sin_val, abs=0.001) == 0.0
        assert pytest.approx(cos_val, abs=0.001) == 1.0

    def test_wind_direction_90_deg(self, engineer):
        """Test wind direction 90° (East)."""
        sin_val, cos_val = engineer._transform_wind_direction(90.0)

        assert pytest.approx(sin_val, abs=0.001) == 1.0
        assert pytest.approx(cos_val, abs=0.001) == 0.0

    def test_wind_direction_180_deg(self, engineer):
        """Test wind direction 180° (South)."""
        sin_val, cos_val = engineer._transform_wind_direction(180.0)

        assert pytest.approx(sin_val, abs=0.001) == 0.0
        assert pytest.approx(cos_val, abs=0.001) == -1.0

    def test_wind_direction_270_deg(self, engineer):
        """Test wind direction 270° (West)."""
        sin_val, cos_val = engineer._transform_wind_direction(270.0)

        assert pytest.approx(sin_val, abs=0.001) == -1.0
        assert pytest.approx(cos_val, abs=0.001) == 0.0

    def test_wind_direction_none(self, engineer):
        """Test wind direction None."""
        sin_val, cos_val = engineer._transform_wind_direction(None)

        assert sin_val is None
        assert cos_val is None


class TestCalendarFeatures:
    """Test calendar-based features."""

    def test_hour_of_day(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test hour_of_day feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert features["hour_of_day"] == 10  # target_time is 10:00

    def test_day_of_week(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test day_of_week feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "day_of_week" in features
        assert 0 <= features["day_of_week"] <= 6

    def test_month(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test month feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert features["month"] == 8  # August

    def test_day_of_year(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test day_of_year feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert "day_of_year" in features
        assert 1 <= features["day_of_year"] <= 365

    def test_is_weekend_weekday(self, engineer):
        """Test is_weekend for weekday."""
        weekday = datetime(2026, 8, 17, 10, 0, 0, tzinfo=timezone.utc)  # Monday
        features = engineer.generate_features(
            target_time=weekday,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["is_weekend"] == 0

    def test_is_weekend_saturday(self, engineer):
        """Test is_weekend for Saturday."""
        saturday = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)  # Saturday
        features = engineer.generate_features(
            target_time=saturday,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["is_weekend"] == 1

    def test_is_weekend_sunday(self, engineer):
        """Test is_weekend for Sunday."""
        sunday = datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc)  # Sunday
        features = engineer.generate_features(
            target_time=sunday,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["is_weekend"] == 1


class TestDomainFeatures:
    """Test domain-specific features."""

    def test_hour_since_midnight(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test hour_since_midnight feature."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert features["hour_since_midnight"] == 10

    def test_season_summer(self, engineer):
        """Test season for summer (June)."""
        june_time = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        features = engineer.generate_features(
            target_time=june_time,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["season"] == 2  # Summer

    def test_season_winter(self, engineer):
        """Test season for winter (January)."""
        jan_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        features = engineer.generate_features(
            target_time=jan_time,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["season"] == 0  # Winter

    def test_season_spring(self, engineer):
        """Test season for spring (April)."""
        apr_time = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        features = engineer.generate_features(
            target_time=apr_time,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["season"] == 1  # Spring

    def test_season_fall(self, engineer):
        """Test season for fall (October)."""
        oct_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
        features = engineer.generate_features(
            target_time=oct_time,
            location_id="kolkata",
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert features["season"] == 3  # Fall


class TestMissingDataHandling:
    """Test missing data imputation."""

    def test_forward_fill_within_3_hours(self, engineer, target_time, location_id):
        """Test forward-fill within 3-hour window."""
        # Missing at -1h, -2h; available at -3h
        facts = {
            (location_id, "pm25", (target_time - timedelta(hours=3)).isoformat()): {
                "observed_value": 60.0,
            },
        }

        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=facts,
            weather_facts={},
        )

        # Should forward-fill from -3h
        assert features["pm25_lag_1h"] == 60.0
        assert features["imputation_count"] >= 2

    def test_citywide_fallback_when_all_missing(
        self, engineer, target_time, location_id, citywide_pm25_baseline
    ):
        """Test city-wide fallback when all location data missing."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
            citywide_pm25_baseline=citywide_pm25_baseline,
        )

        # Should use city-wide median
        assert features["pm25_lag_1h"] == citywide_pm25_baseline["historical_median"]
        assert features["imputation_count"] > 0

    def test_imputation_count_tracked(
        self, engineer, target_time, location_id, citywide_pm25_baseline
    ):
        """Test imputation count is tracked."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts={},  # No data
            weather_facts={},
            citywide_pm25_baseline=citywide_pm25_baseline,
        )

        assert features["imputation_count"] > 0

    def test_no_imputation_with_complete_data(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test no imputation when all data available."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert features["imputation_count"] == 0


class TestFutureLeakagePrevention:
    """Test strict future-leakage prevention."""

    def test_invalid_negative_horizon(self, engineer, target_time, location_id):
        """Test negative horizon raises error."""
        with pytest.raises(ValueError):
            engineer.generate_features(
                target_time=target_time,
                location_id=location_id,
                horizon_minutes=-1,  # Invalid
                hourly_facts={},
                weather_facts={},
            )

    def test_no_future_observation_in_features(
        self, engineer, target_time, location_id
    ):
        """Test features don't use future observations."""
        future_hour = target_time + timedelta(hours=1)

        # Try to inject future data
        facts_with_future = {
            (location_id, "pm25", future_hour.isoformat()): {
                "observed_value": 999.0,  # Marker for future data
            },
        }

        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=facts_with_future,
            weather_facts={},
        )

        # Should NOT use the future observation
        assert features["pm25_lag_1h"] is None or features["pm25_lag_1h"] != 999.0

    def test_target_time_zero_hour_lag(self, engineer, target_time, location_id):
        """Test lags don't access target_time itself."""
        # PM2.5 at target_time should not be used
        facts_at_target = {
            (location_id, "pm25", target_time.isoformat()): {
                "observed_value": 999.0,  # Marker
            },
        }

        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=facts_at_target,
            weather_facts={},
        )

        # Should NOT use data at target_time
        assert features["pm25_lag_1h"] is None or features["pm25_lag_1h"] != 999.0

    def test_rolling_window_before_target_time(
        self, engineer, target_time, location_id
    ):
        """Test rolling windows only use data before target_time."""
        # Create data before and after target_time
        before_time = target_time - timedelta(hours=3)
        after_time = target_time + timedelta(hours=3)

        facts = {
            (location_id, "pm25", before_time.isoformat()): {
                "observed_value": 50.0,
            },
            (location_id, "pm25", after_time.isoformat()): {
                "observed_value": 999.0,  # Should not be used
            },
        }

        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=facts,
            weather_facts={},
        )

        # Rolling mean should only include the before value
        # (and be None or just that value if others are missing)
        rolling_3h = features["pm25_rolling_mean_3h"]
        if rolling_3h is not None:
            # Should be 50.0 or close to it
            assert rolling_3h <= 50.0 or rolling_3h == 999.0 is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_facts_dicts(self, engineer, target_time, location_id):
        """Test empty facts dicts don't crash."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts={},
            weather_facts={},
        )

        assert isinstance(features, dict)
        assert "location_id" in features

    def test_sparse_facts(self, engineer, target_time, location_id):
        """Test sparse facts (only some hours present)."""
        # Only provide 6h and 12h lags
        facts = {
            (location_id, "pm25", (target_time - timedelta(hours=6)).isoformat()): {
                "observed_value": 60.0,
            },
            (location_id, "pm25", (target_time - timedelta(hours=12)).isoformat()): {
                "observed_value": 70.0,
            },
        }

        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=60,
            hourly_facts=facts,
            weather_facts={},
        )

        # 6h and 12h should be populated
        assert features["pm25_lag_6h"] == 60.0
        assert features["pm25_lag_12h"] == 70.0

    def test_horizon_0_minutes(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test horizon of 0 minutes (nowcast)."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=0,  # Nowcast
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert features["horizon_minutes"] == 0

    def test_large_horizon(
        self,
        engineer,
        target_time,
        location_id,
        hourly_pm25_facts,
        hourly_weather_facts,
    ):
        """Test large prediction horizon."""
        features = engineer.generate_features(
            target_time=target_time,
            location_id=location_id,
            horizon_minutes=10080,  # 1 week
            hourly_facts=hourly_pm25_facts,
            weather_facts=hourly_weather_facts,
        )

        assert features["horizon_minutes"] == 10080


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
