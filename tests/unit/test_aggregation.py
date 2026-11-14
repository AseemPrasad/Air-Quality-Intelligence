"""
Unit tests for location-level aggregation from multi-station data.

Tests aggregation logic, coverage calculation, and handling of edge cases.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from aq_engine.analytics.aggregation import LocationAggregator


# --------------------------------------------------
# FIXTURES
# --------------------------------------------------

@pytest.fixture
def aggregator():
    """LocationAggregator with hourly measurement interval."""
    return LocationAggregator(
        storage_root="data/raw",
        measurement_interval_minutes=60,
    )


@pytest.fixture
def three_station_data():
    """Data from 3 stations for testing."""
    return {
        "station_1": [35.0, 36.0, 37.0, 38.0],
        "station_2": [40.0, 41.0, 42.0],
        "station_3": [30.0, 31.0, 32.0, 33.0, 34.0],
    }


@pytest.fixture
def outlier_station_data():
    """Data with one outlier station."""
    return {
        "station_1": [35.0, 36.0, 37.0],
        "station_2": [38.0, 39.0, 40.0],
        "station_3": [500.0, 510.0, 520.0],
    }


@pytest.fixture
def missing_station_data():
    """Data with one missing station."""
    return {
        "station_1": [35.0, 36.0, 37.0],
        "station_2": [38.0, 39.0, 40.0],
    }


# --------------------------------------------------
# MULTI-STATION AGGREGATION
# --------------------------------------------------

class TestMultiStationAggregation:

    def test_three_stations_aggregation(self, aggregator, three_station_data):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(three_station_data.keys())
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    three_station_data[station_id],
                    {
                        "valid": len(three_station_data[station_id]),
                        "suspicious": 0
                    }
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["location_id"] == "kolkata"
        assert result["pollutant"] == "pm25"
        assert result["station_count"] == 3
        assert result["active_stations"] == 3
        assert result["median_value"] is not None
        assert result["observation_count"] == 12

    def test_median_over_mean_robustness(self, aggregator, outlier_station_data):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(outlier_station_data.keys())
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    outlier_station_data[station_id],
                    {
                        "valid": len(outlier_station_data[station_id]),
                        "suspicious": 0
                    }
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["median_value"] < 100
        assert result["mean_value"] > result["median_value"]

    def test_percentile_calculations(self, aggregator, three_station_data):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(three_station_data.keys())
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    three_station_data[station_id],
                    {
                        "valid": len(three_station_data[station_id]),
                        "suspicious": 0
                    }
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["p25"] is not None
        assert result["p75"] is not None
        assert result["p25"] <= result["median_value"]
        assert result["median_value"] <= result["p75"]


# --------------------------------------------------
# COVERAGE CALCULATION
# --------------------------------------------------

class TestCoverageCalculation:

    def test_full_coverage_100_percent(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["s1", "s2", "s3"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    list(range(24)),
                    {"valid": 24, "suspicious": 0}
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="test_loc",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["coverage_pct"] == pytest.approx(
            100.0, abs=0.1
        )

    def test_partial_coverage(self, aggregator, missing_station_data):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["station_1", "station_2", "station_3"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    missing_station_data.get(station_id, []),
                    {
                        "valid": len(
                            missing_station_data.get(station_id, [])
                        ),
                        "suspicious": 0
                    }
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["coverage_pct"] < 100
        assert result["coverage_pct"] > 0

    def test_coverage_zero_no_data(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["s1", "s2", "s3"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                return_value=([], {"valid": 0, "suspicious": 0})
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="empty_loc",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["coverage_pct"] == 0.0
        assert result["observation_count"] == 0


# --------------------------------------------------
# QUALITY TRACKING
# --------------------------------------------------

class TestQualityTracking:

    def test_valid_stations_count(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["s1", "s2"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    [35.0, 36.0],
                    {"valid": 2, "suspicious": 0}
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="test",
                    pollutant="pm25",
                    time_window_hours=1,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["valid_stations"] == 4

    def test_suspicious_stations_count(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["s1", "s2"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    [50.0, 50.0],
                    {"valid": 1, "suspicious": 1}
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="test",
                    pollutant="pm25",
                    time_window_hours=1,
                    end_time=datetime(
                        2026, 8, 15, 12, 0, 0,
                        tzinfo=timezone.utc
                    )
                )

        assert result["valid_stations"] == 2
        assert result["suspicious_stations"] == 2


# --------------------------------------------------
# EDGE CASES
# --------------------------------------------------

class TestEdgeCases:

    def test_single_station(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["s1"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                return_value=(
                    [35.0, 36.0, 37.0],
                    {"valid": 3, "suspicious": 0}
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="single",
                    pollutant="pm25",
                    time_window_hours=24
                )

        assert result["station_count"] == 1
        assert result["active_stations"] == 1
        assert result["median_value"] == 36.0

    def test_no_stations(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=[]
        ):
            result = aggregator.aggregate_stations_to_location(
                location_id="empty",
                pollutant="pm25",
                time_window_hours=24
            )

        assert result["station_count"] == 0
        assert result["median_value"] is None
        assert result["observation_count"] == 0

    def test_all_null_values(self, aggregator):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["s1", "s2"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                return_value=(
                    [],
                    {"valid": 0, "suspicious": 0}
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="nulls",
                    pollutant="pm25",
                    time_window_hours=24
                )

        assert result["median_value"] is None
        assert result["mean_value"] is None


# --------------------------------------------------
# EXPECTED OBSERVATIONS
# --------------------------------------------------

class TestExpectedObservations:

    def test_expected_observations_hourly_measurement(self, aggregator):

        expected = aggregator._calculate_expected_observations(
            station_count=2,
            time_window_hours=24
        )

        assert expected == 48

    def test_expected_observations_15min_interval(self):

        agg = LocationAggregator(
            measurement_interval_minutes=15
        )

        expected = agg._calculate_expected_observations(
            station_count=3,
            time_window_hours=24
        )

        assert expected == 288

    def test_expected_observations_short_window(self, aggregator):

        expected = aggregator._calculate_expected_observations(
            station_count=2,
            time_window_hours=1
        )

        assert expected == 2


# --------------------------------------------------
# BATCH AGGREGATION
# --------------------------------------------------

class TestBatchAggregation:

    def test_batch_aggregation_multiple_pollutants(self, aggregator):

        with patch.object(
            aggregator,
            "aggregate_stations_to_location"
        ) as mock_agg:

            mock_agg.return_value = {
                "location_id": "kolkata",
                "median_value": 40.0,
                "coverage_pct": 95.0
            }

            results = aggregator.aggregate_batch(
                location_id="kolkata",
                pollutants=["pm25", "pm10", "no2"],
                time_window_hours=24
            )

        assert len(results) == 3
        assert mock_agg.call_count == 3

    def test_batch_aggregation_call_order(self, aggregator):

        call_order = []

        def mock_aggregate(location_id, pollutant, **kwargs):
            call_order.append(pollutant)
            return {"pollutant": pollutant}

        with patch.object(
            aggregator,
            "aggregate_stations_to_location",
            side_effect=mock_aggregate
        ):
            aggregator.aggregate_batch(
                location_id="kolkata",
                pollutants=["pm25", "pm10", "o3"],
                time_window_hours=24
            )

        assert call_order == ["pm25", "pm10", "o3"]


# --------------------------------------------------
# PERCENTILE CALCULATION
# --------------------------------------------------

class TestPercentileCalculation:

    def test_percentile_ordering(self, aggregator):

        values = sorted([
            30, 31, 32, 33, 34, 35,
            36, 37, 38, 39, 40
        ])

        p25 = aggregator._percentile(values, 0.25)
        p50 = aggregator._percentile(values, 0.50)
        p75 = aggregator._percentile(values, 0.75)

        assert p25 <= p50 <= p75

    def test_percentile_edge_values(self, aggregator):

        values = sorted([1, 2, 3, 4, 5])

        p0 = aggregator._percentile(values, 0.0)
        p100 = aggregator._percentile(values, 1.0)

        assert p0 == 1.0
        assert p100 == 5.0


# --------------------------------------------------
# OUTPUT FORMAT
# --------------------------------------------------

class TestOutputFormat:

    def test_output_has_required_fields(self, aggregator, three_station_data):

        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(three_station_data.keys())
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    three_station_data[station_id],
                    {
                        "valid": len(three_station_data[station_id]),
                        "suspicious": 0
                    }
                )
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24
                )

        required_fields = [
            "location_id",
            "pollutant",
            "hour_start",
            "station_count",
            "active_stations",
            "median_value",
            "mean_value",
            "p25",
            "p75",
            "max_value",
            "min_value",
            "valid_stations",
            "suspicious_stations",
            "coverage_pct",
            "observation_count",
            "aggregated_at"
        ]

        for field in required_fields:
            assert field in result, f"Missing required field: {field}"


# --------------------------------------------------
# RUN TESTS
# --------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
