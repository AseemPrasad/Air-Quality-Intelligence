"""Unit tests for location-level aggregation from multi-station data.

Tests aggregation logic, coverage calculation, and handling of edge cases.
"""

import pytest
from datetime import datetime, timedelta, timezone, date
from unittest.mock import Mock, patch

from aq_engine.analytics.aggregation import LocationAggregator


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
        "station_1": [35.0, 36.0, 37.0, 38.0],  # 4 obs
        "station_2": [40.0, 41.0, 42.0],  # 3 obs
        "station_3": [30.0, 31.0, 32.0, 33.0, 34.0],  # 5 obs
    }


@pytest.fixture
def outlier_station_data():
    """Data with one outlier station."""
    return {
        "station_1": [35.0, 36.0, 37.0],
        "station_2": [38.0, 39.0, 40.0],
        "station_3": [500.0, 510.0, 520.0],  # Outlier values
    }


@pytest.fixture
def missing_station_data():
    """Data with one missing station."""
    return {
        "station_1": [35.0, 36.0, 37.0],
        "station_2": [38.0, 39.0, 40.0],
        # station_3 is missing
    }


class TestMultiStationAggregation:
    """Test basic multi-station aggregation."""

    def test_three_stations_aggregation(self, aggregator, three_station_data):
        """Test aggregation of 3 stations."""
        with patch.object(
            aggregator, "_get_location_stations", return_value=list(three_station_data.keys())
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    three_station_data[station_id],
                    {"valid": len(three_station_data[station_id]), "suspicious": 0},
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                )

        assert result["location_id"] == "kolkata"
        assert result["pollutant"] == "pm25"
        assert result["station_count"] == 3
        assert result["active_stations"] == 3
        assert result["median_value"] is not None
        assert result["observation_count"] == 12  # 4+3+5

    def test_median_over_mean_robustness(self, aggregator, outlier_station_data):
        """Test median is robust to outliers (prefers median over mean)."""
        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(outlier_station_data.keys()),
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    outlier_station_data[station_id],
                    {"valid": len(outlier_station_data[station_id]), "suspicious": 0},
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                )

        # Median should be around 38-40 (middle values)
        # Mean would be heavily skewed by 500+ values
        assert result["median_value"] < 100  # Should be robust
        assert result["mean_value"] > result["median_value"]  # Mean pulled up by outliers

    def test_percentile_calculations(self, aggregator, three_station_data):
        """Test p25 and p75 calculations."""
        # All values: [30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42]
        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(three_station_data.keys()),
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    three_station_data[station_id],
                    {"valid": len(three_station_data[station_id]), "suspicious": 0},
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                )

        assert result["p25"] is not None
        assert result["p75"] is not None
        assert result["p25"] <= result["median_value"] <= result["p75"]


class TestCoverageCalculation:
    """Test coverage calculation."""

    def test_full_coverage_100_percent(self, aggregator):
        """Test full coverage (100%) when all observations present."""
        station_count = 3
        time_window_hours = 24

        # Expected: (60/60) * 3 * 24 = 72 observations
        # Actual: 72 observations
        with patch.object(aggregator, "_get_location_stations", return_value=["s1", "s2", "s3"]):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    list(range(24)),  # 24 values per station
                    {"valid": 24, "suspicious": 0},
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="test_loc",
                    pollutant="pm25",
                    time_window_hours=24,
                )

        assert result["coverage_pct"] == pytest.approx(100.0, abs=0.1)

    def test_partial_coverage(self, aggregator, missing_station_data):
        """Test partial coverage when station data missing."""
        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=["station_1", "station_2", "station_3"],  # 3 expected
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    missing_station_data.get(station_id, []),  # missing_station_data is missing station_3
                    {
                        "valid": len(missing_station_data.get(station_id, [])),
                        "suspicious": 0,
                    },
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
                    end_time=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                )

        # Expected: (60/60) * 3 * 24 = 72
        # Actual: 6 (only 2 stations reporting)
        assert result["coverage_pct"] < 100
        assert result["coverage_pct"] > 0

    def test_coverage_zero_no_data(self, aggregator):
        """Test coverage is 0% when no data available."""
        with patch.object(
            aggregator, "_get_location_stations", return_value=["s1", "s2", "s3"]
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                return_value=([], {"valid": 0, "suspicious": 0}),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="empty_loc",
                    pollutant="pm25",
                    time_window_hours=24,
                )

        assert result["coverage_pct"] == 0.0
        assert result["observation_count"] == 0


class TestQualityTracking:
    """Test quality (valid/suspicious) station tracking."""

    def test_valid_stations_count(self, aggregator):
        """Test valid_stations count tracking."""
        with patch.object(aggregator, "_get_location_stations", return_value=["s1", "s2"]):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    [35.0, 36.0],  # 2 values per station
                    {"valid": 2, "suspicious": 0},
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="test",
                    pollutant="pm25",
                    time_window_hours=1,
                )

        assert result["valid_stations"] == 4  # 2 * 2 stations

    def test_suspicious_stations_count(self, aggregator):
        """Test suspicious_stations count tracking."""
        with patch.object(aggregator, "_get_location_stations", return_value=["s1", "s2"]):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    [50.0, 50.0],  # Possibly stale round numbers
                    {"valid": 1, "suspicious": 1},  # 1 valid, 1 suspicious per station
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="test",
                    pollutant="pm25",
                    time_window_hours=1,
                )

        assert result["valid_stations"] == 2  # 1 * 2 stations
        assert result["suspicious_stations"] == 2  # 1 * 2 stations


class TestEdgeCases:
    """Test edge cases."""

    def test_single_station(self, aggregator):
        """Test aggregation with single station."""
        with patch.object(aggregator, "_get_location_stations", return_value=["s1"]):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                return_value=([35.0, 36.0, 37.0], {"valid": 3, "suspicious": 0}),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="single",
                    pollutant="pm25",
                    time_window_hours=24,
                )

        assert result["station_count"] == 1
        assert result["active_stations"] == 1
        assert result["median_value"] == 36.0  # Median of [35, 36, 37]

    def test_no_stations(self, aggregator):
        """Test aggregation with no stations defined."""
        with patch.object(aggregator, "_get_location_stations", return_value=[]):
            result = aggregator.aggregate_stations_to_location(
                location_id="empty",
                pollutant="pm25",
                time_window_hours=24,
            )

        assert result["station_count"] == 0
        assert result["median_value"] is None
        assert result["observation_count"] == 0

    def test_all_null_values(self, aggregator):
        """Test with all null values."""
        with patch.object(aggregator, "_get_location_stations", return_value=["s1", "s2"]):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                return_value=([], {"valid": 0, "suspicious": 0}),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="nulls",
                    pollutant="pm25",
                    time_window_hours=24,
                )

        assert result["median_value"] is None
        assert result["mean_value"] is None


class TestExpectedObservations:
    """Test expected observation calculation."""

    def test_expected_observations_hourly_measurement(self, aggregator):
        """Test expected observations with hourly measurement interval."""
        # 60-minute interval, 2 stations, 24 hours
        # Expected = (60/60) * 2 * 24 = 48
        expected = aggregator._calculate_expected_observations(
            station_count=2, time_window_hours=24
        )
        assert expected == 48

    def test_expected_observations_15min_interval(self):
        """Test expected observations with 15-minute interval."""
        agg = LocationAggregator(measurement_interval_minutes=15)
        # 60/15 = 4 obs/hour, 3 stations, 24 hours
        # Expected = 4 * 3 * 24 = 288
        expected = agg._calculate_expected_observations(
            station_count=3, time_window_hours=24
        )
        assert expected == 288

    def test_expected_observations_short_window(self, aggregator):
        """Test expected observations for short time window."""
        # 60-minute interval, 2 stations, 1 hour
        # Expected = (60/60) * 2 * 1 = 2
        expected = aggregator._calculate_expected_observations(
            station_count=2, time_window_hours=1
        )
        assert expected == 2


class TestBatchAggregation:
    """Test batch aggregation of multiple pollutants."""

    def test_batch_aggregation_multiple_pollutants(self, aggregator):
        """Test aggregating multiple pollutants in one call."""
        with patch.object(aggregator, "aggregate_stations_to_location") as mock_agg:
            mock_agg.return_value = {
                "location_id": "kolkata",
                "median_value": 40.0,
                "coverage_pct": 95.0,
            }

            results = aggregator.aggregate_batch(
                location_id="kolkata",
                pollutants=["pm25", "pm10", "no2"],
                time_window_hours=24,
            )

        assert len(results) == 3
        assert mock_agg.call_count == 3

    def test_batch_aggregation_call_order(self, aggregator):
        """Test batch aggregation calls aggregate_stations_to_location in order."""
        call_order = []

        def mock_aggregate(location_id, pollutant, **kwargs):
            call_order.append(pollutant)
            return {"pollutant": pollutant}

        with patch.object(aggregator, "aggregate_stations_to_location", side_effect=mock_aggregate):
            aggregator.aggregate_batch(
                location_id="kolkata",
                pollutants=["pm25", "pm10", "o3"],
                time_window_hours=24,
            )

        assert call_order == ["pm25", "pm10", "o3"]


class TestPercentileCalculation:
    """Test percentile calculation."""

    def test_percentile_ordering(self, aggregator):
        """Test percentiles are correctly ordered."""
        values = sorted([30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40])

        p25 = aggregator._percentile(values, 0.25)
        p50 = aggregator._percentile(values, 0.50)
        p75 = aggregator._percentile(values, 0.75)

        assert p25 <= p50 <= p75

    def test_percentile_edge_values(self, aggregator):
        """Test percentiles with edge values."""
        values = sorted([1, 2, 3, 4, 5])

        p0 = aggregator._percentile(values, 0.0)  # Should be 1
        p100 = aggregator._percentile(values, 1.0)  # Should be 5

        assert p0 == 1.0
        assert p100 == 5.0


class TestOutputFormat:
    """Test output format and required fields."""

    def test_output_has_required_fields(self, aggregator, three_station_data):
        """Test aggregation output includes all required fields."""
        with patch.object(
            aggregator,
            "_get_location_stations",
            return_value=list(three_station_data.keys()),
        ):
            with patch.object(
                aggregator,
                "_get_station_hourly_values",
                side_effect=lambda station_id, **kwargs: (
                    three_station_data[station_id],
                    {"valid": len(three_station_data[station_id]), "suspicious": 0},
                ),
            ):
                result = aggregator.aggregate_stations_to_location(
                    location_id="kolkata",
                    pollutant="pm25",
                    time_window_hours=24,
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
            "aggregated_at",
        ]

        for field in required_fields:
            assert field in result, f"Missing required field: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
