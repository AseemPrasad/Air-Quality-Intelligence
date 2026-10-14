"""Unit tests for feature extraction, forecasting, and aggregation helpers."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import polars as pl
import pytest

from aq_engine.analytics.aggregation import LocationAggregator
from aq_engine.ml.baselines import BaselineForecaster
from aq_engine.ml.features import FeatureEngineer
from aq_engine.storage.analytics_engine import ParquetAnalyticsEngine


@pytest.fixture
def target_time():
    return datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def pm25_facts(target_time):
    return {
        ("loc", "pm25", (target_time - timedelta(hours=hours)).isoformat()): {
            "observed_value": float(10 + hours)
        }
        for hours in range(1, 25)
    }


@pytest.fixture
def weather_facts(target_time):
    fields = {
        "temperature_c": 10.0,
        "humidity_pct": 20.0,
        "wind_speed_ms": 30.0,
        "pressure_hpa": 40.0,
        "wind_direction_deg": 50.0,
    }
    return {
        ("loc", (target_time - timedelta(hours=hours)).isoformat()): {
            name: value + hours for name, value in fields.items()
        }
        for hours in range(1, 25)
    }


def test_extract_pm25_lags_reads_configured_hours():
    engineer = FeatureEngineer()
    target_time = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    facts = {
        ("loc", "pm25", (target_time - timedelta(hours=hours)).isoformat()): {
            "observed_value": float(hours * 10)
        }
        for hours in engineer.PM25_LAG_HOURS
    }

    features, imputations = engineer._extract_pm25_lags(
        target_time, "loc", facts, None
    )

    assert features == {
        f"pm25_lag_{hours}h": float(hours * 10)
        for hours in engineer.PM25_LAG_HOURS
    }
    assert imputations == 0


def test_extract_pm25_lags_uses_forward_fill_and_citywide_fallback(target_time):
    engineer = FeatureEngineer()
    facts = {
        ("loc", "pm25", (target_time - timedelta(hours=2)).isoformat()): {
            "observed_value": 22.0
        }
    }
    features, imputations = engineer._extract_pm25_lags(
        target_time,
        "loc",
        facts,
        {"historical_median": 55.0},
    )

    assert features["pm25_lag_1h"] == 22.0
    assert features["pm25_lag_2h"] == 22.0
    assert features["pm25_lag_3h"] == 55.0
    assert features["pm25_lag_24h"] == 55.0
    assert imputations == len(engineer.PM25_LAG_HOURS) - 1


def test_extract_pm25_lags_leaves_missing_values_without_fallback(target_time):
    features, imputations = FeatureEngineer()._extract_pm25_lags(
        target_time, "loc", {}, None
    )

    assert len(features) == 6
    assert all(value is None for value in features.values())
    assert imputations == 0


def test_extract_weather_lags_reads_all_weather_fields(target_time, weather_facts):
    features, imputations = FeatureEngineer()._extract_weather_lags(
        target_time, "loc", weather_facts, None
    )

    assert features == {
        "temp_lag_1h": 11.0,
        "humidity_lag_1h": 21.0,
        "wind_speed_lag_1h": 31.0,
        "pressure_lag_1h": 41.0,
        "wind_direction_deg_lag_1h": 51.0,
    }
    assert imputations == 0


def test_extract_weather_lags_uses_forward_fill_and_citywide_fallback(target_time):
    field = "temperature_c"
    facts = {
        ("loc", (target_time - timedelta(hours=2)).isoformat()): {field: 18.0}
    }
    baseline = {
        "temperature_c_mean": 25.0,
        "humidity_pct_mean": 60.0,
        "wind_speed_ms_mean": 5.0,
        "pressure_hpa_mean": 1012.0,
        "wind_direction_deg_mean": 200.0,
    }

    features, imputations = FeatureEngineer()._extract_weather_lags(
        target_time, "loc", facts, baseline
    )

    assert features["temp_lag_1h"] == 18.0
    assert features["humidity_lag_1h"] == 60.0
    assert features["wind_direction_deg_lag_1h"] == 200.0
    assert imputations == 5


def test_extract_weather_lags_returns_none_without_fallback(target_time):
    features, imputations = FeatureEngineer()._extract_weather_lags(
        target_time, "loc", {}, None
    )

    assert len(features) == 5
    assert all(value is None for value in features.values())
    assert imputations == 0


def test_extract_pm25_rolling_statistics_calculates_mean_std_and_max(
    target_time, pm25_facts
):
    features, imputations = FeatureEngineer()._extract_pm25_rolling_statistics(
        target_time, "loc", pm25_facts, None
    )

    assert features["pm25_rolling_mean_3h"] == pytest.approx(12.0)
    assert features["pm25_rolling_mean_6h"] == pytest.approx(13.5)
    assert features["pm25_rolling_mean_12h"] == pytest.approx(16.5)
    assert features["pm25_rolling_mean_24h"] == pytest.approx(22.5)
    assert features["pm25_rolling_std_6h"] == pytest.approx((35 / 12) ** 0.5)
    assert features["pm25_rolling_std_24h"] == pytest.approx((575 / 12) ** 0.5)
    assert features["pm25_rolling_max_24h"] == 34.0
    assert imputations == 0


def test_extract_pm25_rolling_statistics_uses_fallbacks_for_empty_windows(target_time):
    features, imputations = FeatureEngineer()._extract_pm25_rolling_statistics(
        target_time,
        "loc",
        {},
        {"historical_median": 40.0, "p99": 90.0},
    )

    for hours in (3, 6, 12, 24):
        assert features[f"pm25_rolling_mean_{hours}h"] == 40.0
    assert features["pm25_rolling_std_6h"] == 0.0
    assert features["pm25_rolling_std_24h"] == 0.0
    assert features["pm25_rolling_max_24h"] == 90.0
    assert imputations == 5


def test_extract_pm25_rolling_statistics_empty_without_fallback(target_time):
    features, imputations = FeatureEngineer()._extract_pm25_rolling_statistics(
        target_time, "loc", {}, None
    )

    assert features["pm25_rolling_mean_3h"] is None
    assert features["pm25_rolling_mean_24h"] is None
    assert features["pm25_rolling_std_6h"] == 0.0
    assert features["pm25_rolling_std_24h"] == 0.0
    assert features["pm25_rolling_max_24h"] is None
    assert imputations == 0


def test_extract_weather_rolling_statistics_calculates_means(
    target_time, weather_facts
):
    features, imputations = FeatureEngineer()._extract_weather_rolling_statistics(
        target_time, "loc", weather_facts, None
    )

    assert features["temp_rolling_mean_6h"] == pytest.approx(13.5)
    assert features["temp_rolling_mean_24h"] == pytest.approx(22.5)
    assert features["humidity_rolling_mean_6h"] == pytest.approx(23.5)
    assert features["wind_speed_rolling_mean_24h"] == pytest.approx(42.5)
    assert features["pressure_rolling_mean_24h"] == pytest.approx(52.5)
    assert len(features) == 8
    assert imputations == 0


def test_extract_weather_rolling_statistics_uses_baseline_for_empty_windows(
    target_time,
):
    baseline = {
        "temperature_c_mean": 20.0,
        "humidity_pct_mean": 50.0,
        "wind_speed_ms_mean": 6.0,
        "pressure_hpa_mean": 1010.0,
    }
    features, imputations = FeatureEngineer()._extract_weather_rolling_statistics(
        target_time, "loc", {}, baseline
    )

    assert features["temp_rolling_mean_6h"] == 20.0
    assert features["humidity_rolling_mean_24h"] == 50.0
    assert features["wind_speed_rolling_mean_6h"] == 6.0
    assert features["pressure_rolling_mean_24h"] == 1010.0
    assert len(features) == 8
    assert imputations == 8


def test_extract_weather_rolling_statistics_leaves_empty_values_none(target_time):
    features, imputations = FeatureEngineer()._extract_weather_rolling_statistics(
        target_time, "loc", {}, None
    )

    assert len(features) == 8
    assert all(value is None for value in features.values())
    assert imputations == 0


def test_rolling_mean_forecast_calculates_mean_and_high_confidence(target_time):
    values = {
        (target_time - timedelta(days=days)).isoformat(): float(days * 10)
        for days in range(1, 6)
    }

    result = BaselineForecaster().rolling_mean_forecast(
        "loc", target_time, values, window_days=5
    )

    assert result == {
        "predicted_pm25": 30.0,
        "baseline_type": "rolling_mean_5d",
        "confidence": "high",
        "values_used": 5,
        "window_days": 5,
    }


@pytest.mark.parametrize(
    ("values_used", "expected_confidence"),
    [(4, "medium"), (2, "low"), (0, "low")],
)
def test_rolling_mean_forecast_confidence_and_empty_window(
    target_time, values_used, expected_confidence
):
    values = {
        (target_time - timedelta(days=days)).isoformat(): float(days)
        for days in range(1, values_used + 1)
    }

    result = BaselineForecaster().rolling_mean_forecast(
        "loc", target_time, values, window_days=5
    )

    assert result["confidence"] == expected_confidence
    assert result["values_used"] == values_used
    expected_mean = (values_used + 1) / 2 if values_used else None
    assert result["predicted_pm25"] == (
        pytest.approx(expected_mean) if expected_mean is not None else None
    )


def test_rolling_mean_forecast_ignores_none_and_current_target_value(target_time):
    values = {
        (target_time - timedelta(days=1)).isoformat(): None,
        (target_time - timedelta(days=2)).isoformat(): 30.0,
        target_time.isoformat(): 999.0,
    }

    result = BaselineForecaster().rolling_mean_forecast(
        "loc", target_time, values, window_days=2
    )

    assert result["predicted_pm25"] == 30.0
    assert result["values_used"] == 1
    assert result["confidence"] == "low"


def test_execute_time_window_aggregation_returns_dataframe_and_builds_query(tmp_path):
    engine = ParquetAnalyticsEngine(data_dir=str(tmp_path))
    expected = pl.DataFrame(
        {
            "location_id": ["loc"],
            "hour_bucket": [datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)],
            "mean_concentration": [25.0],
            "peak_concentration": [40.0],
        }
    )
    connection = MagicMock()
    connection.execute.return_value.pl.return_value = expected
    engine.conn = connection

    try:
        result = engine.execute_time_window_aggregation("pm25", days_lookback=3)
    finally:
        engine.close()

    assert result.equals(expected)
    query = connection.execute.call_args.args[0]
    assert "**/*pm25*.parquet" in query
    assert "INTERVAL 3 DAY" in query
    assert "AVG(observed_value)" in query
    assert "MAX(observed_value)" in query
    assert "GROUP BY 1, 2" in query


def test_execute_time_window_aggregation_reraises_query_errors(tmp_path):
    engine = ParquetAnalyticsEngine(data_dir=str(tmp_path))
    connection = MagicMock()
    connection.execute.side_effect = RuntimeError("DuckDB query failed")
    engine.conn = connection

    try:
        with pytest.raises(RuntimeError, match="DuckDB query failed"):
            engine.execute_time_window_aggregation("pm25")
    finally:
        engine.close()


def test_aggregate_stations_to_location_calculates_statistics_and_coverage(
    target_time,
):
    aggregator = LocationAggregator(measurement_interval_minutes=60)
    station_values = {"s1": [10.0, 20.0], "s2": [30.0, 40.0]}
    aggregator._get_location_stations = MagicMock(return_value=["s1", "s2"])
    aggregator._get_station_hourly_values = MagicMock(
        side_effect=lambda station_id, **kwargs: (
            station_values[station_id],
            {"valid": 2, "suspicious": 0},
        )
    )

    result = aggregator.aggregate_stations_to_location(
        "loc", "pm25", time_window_hours=2, end_time=target_time
    )

    assert result["location_id"] == "loc"
    assert result["pollutant"] == "pm25"
    assert result["hour_start"] == (target_time - timedelta(hours=2)).isoformat()
    assert result["station_count"] == 2
    assert result["active_stations"] == 2
    assert result["median_value"] == 25.0
    assert result["mean_value"] == 25.0
    assert result["p25"] == 17.5
    assert result["p75"] == 32.5
    assert result["min_value"] == 10.0
    assert result["max_value"] == 40.0
    assert result["observation_count"] == 4
    assert result["expected_observation_count"] == 4
    assert result["coverage_pct"] == 100.0
    for call in aggregator._get_station_hourly_values.call_args_list:
        assert call.kwargs["start_time"] == target_time - timedelta(hours=2)
        assert call.kwargs["end_time"] == target_time


def test_aggregate_stations_to_location_returns_empty_result_without_stations(
    target_time,
):
    aggregator = LocationAggregator()
    aggregator._get_location_stations = MagicMock(return_value=[])

    result = aggregator.aggregate_stations_to_location(
        "loc", "pm25", time_window_hours=1, end_time=target_time
    )

    assert result["location_id"] == "loc"
    assert result["pollutant"] == "pm25"
    assert result["station_count"] == 0
    assert result["active_stations"] == 0
    assert result["median_value"] is None
    assert result["observation_count"] == 0


def test_aggregate_stations_to_location_returns_empty_result_when_stations_have_no_data(
    target_time,
):
    aggregator = LocationAggregator()
    aggregator._get_location_stations = MagicMock(return_value=["s1", "s2"])
    aggregator._get_station_hourly_values = MagicMock(
        return_value=([], {"valid": 0, "suspicious": 0})
    )

    result = aggregator.aggregate_stations_to_location(
        "loc", "pm25", time_window_hours=1, end_time=target_time
    )

    assert result["station_count"] == 2
    assert result["active_stations"] == 0
    assert result["median_value"] is None
    assert result["coverage_pct"] == 0.0


def test_aggregate_stations_to_location_filters_none_values_and_counts_quality(
    target_time,
):
    aggregator = LocationAggregator(measurement_interval_minutes=30)
    aggregator._get_location_stations = MagicMock(return_value=["s1"])
    aggregator._get_station_hourly_values = MagicMock(
        return_value=([10.0, None, 30.0], {"valid": 1, "suspicious": 1})
    )

    result = aggregator.aggregate_stations_to_location(
        "loc", "pm25", time_window_hours=2, end_time=target_time
    )

    assert result["observation_count"] == 2
    assert result["min_value"] == 10.0
    assert result["max_value"] == 30.0
    assert result["valid_stations"] == 1
    assert result["suspicious_stations"] == 1
    assert result["expected_observation_count"] == 4
    assert result["coverage_pct"] == 50.0


def test_pm25_lags_exclude_current_row_target_value(target_time, pm25_facts):
    pm25_facts[("loc", "pm25", target_time.isoformat())] = {
        "observed_value": 10000.0
    }

    features, _ = FeatureEngineer()._extract_pm25_lags(
        target_time, "loc", pm25_facts, None
    )

    assert features["pm25_lag_1h"] == 11.0
    assert features["pm25_lag_24h"] == 34.0
    assert 10000.0 not in features.values()


def test_pm25_rolling_statistics_exclude_current_row_target_value(
    target_time, pm25_facts
):
    pm25_facts[("loc", "pm25", target_time.isoformat())] = {
        "observed_value": 10000.0
    }
    pm25_facts[
        ("loc", "pm25", (target_time - timedelta(hours=25)).isoformat())
    ] = {"observed_value": 20000.0}

    features, _ = FeatureEngineer()._extract_pm25_rolling_statistics(
        target_time, "loc", pm25_facts, None
    )

    assert features["pm25_rolling_mean_3h"] == pytest.approx(12.0)
    assert features["pm25_rolling_mean_24h"] == pytest.approx(22.5)
    assert features["pm25_rolling_max_24h"] == 34.0


def test_weather_lags_exclude_current_row_target_value(target_time, weather_facts):
    weather_facts[("loc", target_time.isoformat())] = {
        "temperature_c": 10000.0,
        "humidity_pct": 10000.0,
        "wind_speed_ms": 10000.0,
        "pressure_hpa": 10000.0,
        "wind_direction_deg": 10000.0,
    }

    features, _ = FeatureEngineer()._extract_weather_lags(
        target_time, "loc", weather_facts, None
    )

    assert features["temp_lag_1h"] == 11.0
    assert features["humidity_lag_1h"] == 21.0
    assert 10000.0 not in features.values()


def test_weather_rolling_statistics_exclude_current_row_target_value(
    target_time, weather_facts
):
    weather_facts[("loc", target_time.isoformat())] = {
        "temperature_c": 10000.0,
        "humidity_pct": 10000.0,
        "wind_speed_ms": 10000.0,
        "pressure_hpa": 10000.0,
    }

    features, _ = FeatureEngineer()._extract_weather_rolling_statistics(
        target_time, "loc", weather_facts, None
    )

    assert features["temp_rolling_mean_6h"] == pytest.approx(13.5)
    assert features["pressure_rolling_mean_6h"] == pytest.approx(43.5)
    assert 10000.0 not in features.values()


def test_pm25_lag_single_row_and_missing_timestamps(target_time):
    facts = {
        ("loc", "pm25", (target_time - timedelta(hours=1)).isoformat()): {
            "observed_value": 0.0
        }
    }

    features, imputations = FeatureEngineer()._extract_pm25_lags(
        target_time, "loc", facts, None
    )

    assert features["pm25_lag_1h"] == 0.0
    assert all(
        features[f"pm25_lag_{hours}h"] is None
        for hours in (2, 3, 6, 12, 24)
    )
    assert imputations == 0


def test_pm25_lag_forward_fill_includes_three_hour_boundary(target_time):
    facts = {
        ("loc", "pm25", (target_time - timedelta(hours=4)).isoformat()): {
            "observed_value": 44.0
        }
    }

    features, imputations = FeatureEngineer()._extract_pm25_lags(
        target_time, "loc", facts, None
    )

    assert features["pm25_lag_1h"] == 44.0
    assert imputations == 3


def test_weather_lag_single_row_and_missing_timestamps(target_time):
    facts = {
        ("loc", (target_time - timedelta(hours=1)).isoformat()): {
            "temperature_c": 0.0
        }
    }

    features, imputations = FeatureEngineer()._extract_weather_lags(
        target_time, "loc", facts, None
    )

    assert features["temp_lag_1h"] == 0.0
    assert all(
        features[name] is None
        for name in (
            "humidity_lag_1h",
            "wind_speed_lag_1h",
            "pressure_lag_1h",
            "wind_direction_deg_lag_1h",
        )
    )
    assert imputations == 0


def test_weather_lag_forward_fill_includes_three_hour_boundary(target_time):
    facts = {
        ("loc", (target_time - timedelta(hours=4)).isoformat()): {
            "temperature_c": 18.0
        }
    }

    features, imputations = FeatureEngineer()._extract_weather_lags(
        target_time, "loc", facts, None
    )

    assert features["temp_lag_1h"] == 18.0
    assert imputations == 1


def test_pm25_rolling_statistics_handle_single_row_and_window_boundaries(
    target_time,
):
    facts = {
        ("loc", "pm25", (target_time - timedelta(hours=1)).isoformat()): {
            "observed_value": 0.0
        },
        ("loc", "pm25", (target_time - timedelta(hours=25)).isoformat()): {
            "observed_value": 1000.0
        },
    }

    features, imputations = FeatureEngineer()._extract_pm25_rolling_statistics(
        target_time, "loc", facts, None
    )

    assert features["pm25_rolling_mean_3h"] == 0.0
    assert features["pm25_rolling_mean_24h"] == 0.0
    assert features["pm25_rolling_std_6h"] == 0.0
    assert features["pm25_rolling_std_24h"] == 0.0
    assert features["pm25_rolling_max_24h"] == 0.0
    assert imputations == 0


def test_weather_rolling_statistics_handle_single_row_and_missing_timestamps(
    target_time,
):
    facts = {
        ("loc", (target_time - timedelta(hours=1)).isoformat()): {
            "temperature_c": 0.0
        }
    }

    features, imputations = FeatureEngineer()._extract_weather_rolling_statistics(
        target_time, "loc", facts, None
    )

    assert features["temp_rolling_mean_6h"] == 0.0
    assert features["temp_rolling_mean_24h"] == 0.0
    assert features["humidity_rolling_mean_6h"] is None
    assert features["pressure_rolling_mean_24h"] is None
    assert imputations == 0


def test_rolling_mean_forecast_single_value_at_window_boundary(target_time):
    values = {
        (target_time - timedelta(days=1)).isoformat(): 0.0,
        (target_time - timedelta(days=2)).isoformat(): 1000.0,
        (target_time + timedelta(days=1)).isoformat(): 2000.0,
    }

    result = BaselineForecaster().rolling_mean_forecast(
        "loc", target_time, values, window_days=1
    )

    assert result["predicted_pm25"] == 0.0
    assert result["values_used"] == 1
    assert result["confidence"] == "high"


def test_execute_time_window_aggregation_returns_empty_dataframe_for_no_rows(
    tmp_path,
):
    engine = ParquetAnalyticsEngine(data_dir=str(tmp_path))
    empty = pl.DataFrame(
        schema={
            "location_id": pl.String,
            "hour_bucket": pl.Datetime(time_zone="UTC"),
            "mean_concentration": pl.Float64,
            "peak_concentration": pl.Float64,
        }
    )
    connection = MagicMock()
    connection.execute.return_value.pl.return_value = empty
    engine.conn = connection

    try:
        result = engine.execute_time_window_aggregation("pm25", days_lookback=0)
    finally:
        engine.close()

    assert result.is_empty()
    query = connection.execute.call_args.args[0]
    assert "INTERVAL 0 DAY" in query


def test_aggregate_stations_to_location_handles_single_boundary_value(target_time):
    aggregator = LocationAggregator(measurement_interval_minutes=60)
    aggregator._get_location_stations = MagicMock(return_value=["s1"])
    aggregator._get_station_hourly_values = MagicMock(
        return_value=([0.0], {"valid": 1, "suspicious": 0})
    )

    result = aggregator.aggregate_stations_to_location(
        "loc", "pm25", time_window_hours=1, end_time=target_time
    )

    assert result["station_count"] == 1
    assert result["active_stations"] == 1
    assert result["median_value"] == 0.0
    assert result["mean_value"] == 0.0
    assert result["p25"] == 0.0
    assert result["p75"] == 0.0
    assert result["min_value"] == 0.0
    assert result["max_value"] == 0.0
    assert result["coverage_pct"] == 100.0


def test_aggregate_stations_to_location_reports_sparse_timestamp_coverage(
    target_time,
):
    aggregator = LocationAggregator(measurement_interval_minutes=60)
    aggregator._get_location_stations = MagicMock(return_value=["s1"])
    aggregator._get_station_hourly_values = MagicMock(
        return_value=([15.0], {"valid": 1, "suspicious": 0})
    )

    result = aggregator.aggregate_stations_to_location(
        "loc", "pm25", time_window_hours=3, end_time=target_time
    )

    assert result["observation_count"] == 1
    assert result["expected_observation_count"] == 3
    assert result["coverage_pct"] == pytest.approx(100 / 3)
