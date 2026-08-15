"""Unit tests for baseline forecasting models."""

import pytest
import statistics
from datetime import datetime, timezone, timedelta

from aq_engine.ml.baselines import BaselineForecaster


@pytest.fixture
def forecaster():
    """BaselineForecaster instance."""
    return BaselineForecaster()


@pytest.fixture
def target_time():
    """Target time for forecasts."""
    return datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def location_id():
    """Location identifier."""
    return "kolkata"


@pytest.fixture
def sample_hourly_values(target_time):
    """Sample hourly PM2.5 values."""
    values = {}
    for hours_back in range(1, 25):
        time = target_time - timedelta(hours=hours_back)
        key = time.isoformat()
        values[key] = 50.0 + hours_back
    return values


class TestNaiveCurrentValue:
    """Test naive current value (persistence) forecast."""

    def test_naive_predicts_value_at_minus_horizon(
        self, forecaster, location_id, target_time, sample_hourly_values
    ):
        """Test naive forecast uses value at (target_time - horizon)."""
        result = forecaster.naive_current_value(
            location_id=location_id,
            target_time=target_time,
            horizon_minutes=60,
            hourly_pm25_values=sample_hourly_values,
        )
        assert result["predicted_pm25"] == 51.0

    def test_naive_baseline_type(
        self, forecaster, location_id, target_time, sample_hourly_values
    ):
        """Test naive forecast has correct baseline_type."""
        result = forecaster.naive_current_value(
            location_id=location_id,
            target_time=target_time,
            horizon_minutes=60,
            hourly_pm25_values=sample_hourly_values,
        )
        assert result["baseline_type"] == "naive_current_value"

    def test_naive_confidence_high_with_data(
        self, forecaster, location_id, target_time, sample_hourly_values
    ):
        """Test naive forecast has high confidence when data available."""
        result = forecaster.naive_current_value(
            location_id=location_id,
            target_time=target_time,
            horizon_minutes=60,
            hourly_pm25_values=sample_hourly_values,
        )
        assert result["confidence"] == "high"


class TestSameHourYesterday:
    """Test same-hour-yesterday forecast."""

    def test_same_hour_yesterday_uses_24h_lag(
        self, forecaster, location_id, target_time, sample_hourly_values
    ):
        """Test same-hour-yesterday uses observation from (target_time - 24h)."""
        result = forecaster.same_hour_yesterday(
            location_id=location_id,
            target_time=target_time,
            hourly_pm25_values=sample_hourly_values,
        )
        assert result["predicted_pm25"] == 74.0

    def test_same_hour_yesterday_baseline_type(
        self, forecaster, location_id, target_time, sample_hourly_values
    ):
        """Test same-hour-yesterday has correct baseline_type."""
        result = forecaster.same_hour_yesterday(
            location_id=location_id,
            target_time=target_time,
            hourly_pm25_values=sample_hourly_values,
        )
        assert result["baseline_type"] == "same_hour_yesterday"


class TestRollingMeanForecast:
    """Test rolling mean forecast."""

    def test_rolling_mean_calculates_mean_correctly(
        self, forecaster, location_id, target_time
    ):
        """Test rolling mean calculates correct average."""
        values = {}
        expected_values = []
        for day_offset in range(1, 8):
            time = target_time - timedelta(days=day_offset)
            key = time.isoformat()
            value = 50.0 + day_offset
            values[key] = value
            expected_values.append(value)
        result = forecaster.rolling_mean_forecast(
            location_id=location_id,
            target_time=target_time,
            hourly_pm25_values=values,
            window_days=7,
        )
        expected_mean = statistics.mean(expected_values)
        assert pytest.approx(result["predicted_pm25"], abs=0.01) == expected_mean

    def test_rolling_mean_7_day_window(
        self, forecaster, location_id, target_time
    ):
        """Test rolling mean uses 7-day window."""
        values = {}
        for day_offset in range(1, 8):
            time = target_time - timedelta(days=day_offset)
            key = time.isoformat()
            values[key] = 50.0 + day_offset

        result = forecaster.rolling_mean_forecast(
            location_id=location_id,
            target_time=target_time,
            hourly_pm25_values=values,
        )
        assert result["window_days"] == 7
        assert result["values_used"] == 7

    def test_rolling_mean_baseline_type(
        self, forecaster, location_id, target_time
    ):
        """Test rolling mean has correct baseline_type."""
        values = {}
        for day_offset in range(1, 8):
            time = target_time - timedelta(days=day_offset)
            key = time.isoformat()
            values[key] = 50.0 + day_offset

        result = forecaster.rolling_mean_forecast(
            location_id=location_id,
            target_time=target_time,
            hourly_pm25_values=values,
            window_days=7,
        )
        assert result["baseline_type"] == "rolling_mean_7d"


class TestBaselineEvaluation:
    """Test baseline evaluation metrics."""

    def test_evaluate_baseline_mae(self, forecaster):
        """Test MAE calculation."""
        predictions = [50.0, 52.0, 48.0, 55.0]
        actuals = [51.0, 50.0, 50.0, 52.0]
        result = forecaster.evaluate_baseline(predictions, actuals)
        expected_mae = 2.0
        assert pytest.approx(result["mae"], abs=0.01) == expected_mae

    def test_evaluate_baseline_rmse(self, forecaster):
        """Test RMSE calculation."""
        predictions = [50.0, 52.0, 48.0, 55.0]
        actuals = [51.0, 50.0, 50.0, 52.0]
        result = forecaster.evaluate_baseline(predictions, actuals)
        expected_rmse = (4.5) ** 0.5
        assert pytest.approx(result["rmse"], abs=0.01) == expected_rmse

    def test_evaluate_baseline_with_none_values(self, forecaster):
        """Test evaluation filters out None predictions."""
        predictions = [50.0, None, 48.0, None, 55.0]
        actuals = [51.0, 50.0, 50.0, 52.0, 52.0]
        result = forecaster.evaluate_baseline(predictions, actuals)
        assert result["valid_count"] == 3


class TestCompareBaselines:
    """Test baseline comparison."""

    def test_compare_baselines_finds_best(self, forecaster):
        """Test compare_baselines finds best performing baseline."""
        baseline_results = {
            "naive": {"mae": 3.5, "rmse": 4.2},
            "same_hour_yesterday": {"mae": 2.8, "rmse": 3.5},
            "rolling_mean": {"mae": 2.5, "rmse": 3.1},
        }
        best_type, best_mae = forecaster.compare_baselines(baseline_results)
        assert best_type == "rolling_mean"
        assert best_mae == 2.5


class TestImprovementThreshold:
    """Test ML model improvement threshold."""

    def test_improvement_threshold_5_percent(self, forecaster):
        """Test 5% improvement threshold (default)."""
        best_baseline_mae = 3.0
        threshold = forecaster.improvement_threshold(best_baseline_mae, min_improvement_pct=5.0)
        expected_threshold = 2.85
        assert pytest.approx(threshold, abs=0.01) == expected_threshold

    def test_improvement_threshold_10_percent(self, forecaster):
        """Test 10% improvement threshold."""
        best_baseline_mae = 3.0
        threshold = forecaster.improvement_threshold(best_baseline_mae, min_improvement_pct=10.0)
        expected_threshold = 2.7
        assert pytest.approx(threshold, abs=0.01) == expected_threshold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
