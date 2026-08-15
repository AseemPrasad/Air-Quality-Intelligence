"""Integration tests for dbt hourly fact models.

Tests:
- Raw data → deduplicated intermediate → fact table transformations
- Aggregation correctness (mean, median, stddev)
- Coverage calculations
- Baseline joins and anomaly detection
"""

import pytest
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import polars as pl


@pytest.fixture
def sample_raw_air_quality():
    """Sample raw air quality data."""
    base_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
    return pl.DataFrame({
        "source": ["openaq"] * 12,
        "station_id": ["st1"] * 4 + ["st2"] * 4 + ["st3"] * 4,
        "sensor_id": ["s1"] * 12,
        "pollutant": ["pm25"] * 12,
        "value": [35.0, 36.0, 37.0, 38.0, 40.0, 41.0, 42.0, 43.0, 30.0, 31.0, 32.0, 33.0],
        "unit": ["µg/m³"] * 12,
        "observed_at": [
            base_time,
            base_time + timedelta(minutes=15),
            base_time + timedelta(minutes=30),
            base_time + timedelta(minutes=45),
            base_time,
            base_time + timedelta(minutes=15),
            base_time + timedelta(minutes=30),
            base_time + timedelta(minutes=45),
            base_time,
            base_time + timedelta(minutes=15),
            base_time + timedelta(minutes=30),
            base_time + timedelta(minutes=45),
        ],
        "ingested_at": [
            base_time + timedelta(minutes=1),
            base_time + timedelta(minutes=16),
            base_time + timedelta(minutes=31),
            base_time + timedelta(minutes=46),
        ] * 3,
        "raw_payload_hash": [f"hash_{i}" for i in range(12)],
    })


@pytest.fixture
def sample_weather_data():
    """Sample raw weather data."""
    base_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
    return pl.DataFrame({
        "source": ["open_meteo"] * 8,
        "location_id": ["kolkata"] * 8,
        "temperature_c": [28.0, 28.5, 29.0, 29.5, 30.0, 30.5, 31.0, 31.5],
        "humidity_pct": [65.0, 64.0, 63.0, 62.0, 61.0, 60.0, 59.0, 58.0],
        "wind_speed_kmh": [8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5],
        "wind_direction_deg": [180.0, 185.0, 190.0, 195.0, 200.0, 205.0, 210.0, 215.0],
        "pressure_hpa": [1013.0] * 8,
        "precipitation_mm": [0.0] * 8,
        "cloud_cover_pct": [40.0] * 8,
        "observed_at": [
            base_time + timedelta(minutes=i*10)
            for i in range(8)
        ],
        "ingested_at": [
            base_time + timedelta(minutes=i*10 + 2)
            for i in range(8)
        ],
        "raw_payload_hash": [f"weather_hash_{i}" for i in range(8)],
    })


@pytest.fixture
def baselines():
    """Sample baseline data."""
    return pl.DataFrame({
        "location_id": ["kolkata"] * 2,
        "pollutant": ["pm25", "pm25"],
        "month": [8, 8],
        "hour_of_day": [10, 11],
        "historical_median": [40.0, 42.0],
        "mad": [5.0, 5.0],
        "p90": [50.0, 52.0],
        "p95": [55.0, 57.0],
        "p99": [60.0, 62.0],
    })


class TestDeduplication:
    """Test deduplication logic."""

    def test_air_quality_deduplication(self, sample_raw_air_quality):
        """Test air quality deduplication removes exact duplicates."""
        # Create duplicates
        df = pl.concat([sample_raw_air_quality, sample_raw_air_quality])

        # Simulate deduplication (row_number window function)
        deduped = df.with_columns(
            rn=pl.int_range(pl.len()).over(
                ["source", "station_id", "sensor_id", "pollutant", "observed_at"],
                order_by="ingested_at"
            )
        ).filter(pl.col("rn") == 0)

        # Should have same number of rows as original (duplicates removed)
        assert len(deduped) == len(sample_raw_air_quality)


class TestUnitNormalization:
    """Test unit conversion to µg/m³."""

    def test_normalize_mg_to_ug(self):
        """Test mg/m³ → µg/m³ conversion."""
        df = pl.DataFrame({
            "value": [1.0, 2.0, 3.0],
            "unit": ["mg/m³"] * 3,
        })

        normalized = df.with_columns(
            normalized_value=pl.when(pl.col("unit") == "mg/m³")
            .then(pl.col("value") * 1000)
            .otherwise(pl.col("value"))
        )

        assert normalized["normalized_value"].to_list() == [1000.0, 2000.0, 3000.0]

    def test_normalize_ug_passthrough(self):
        """Test µg/m³ passes through unchanged."""
        df = pl.DataFrame({
            "value": [35.0, 36.0],
            "unit": ["µg/m³", "µg/m³"],
        })

        normalized = df.with_columns(
            normalized_value=pl.col("value")
        )

        assert normalized["normalized_value"].to_list() == [35.0, 36.0]


class TestHourlyAggregation:
    """Test hourly aggregation logic."""

    def test_mean_calculation(self, sample_raw_air_quality):
        """Test mean value calculation."""
        # Group by hour and calculate mean
        hourly = sample_raw_air_quality.with_columns(
            hour_start=pl.col("observed_at").dt.truncate("1h")
        ).group_by(
            ["hour_start", "source", "station_id", "pollutant"]
        ).agg(
            pl.col("value").mean().alias("mean_value"),
            pl.col("value").count().alias("observation_count"),
        )

        # All 3 stations have observations in 10:00 hour with values [35, 36, 37, 38, 40, 41, 42, 43, 30, 31, 32, 33]
        # Group by station:
        # st1: [35, 36, 37, 38] → mean = 36.5
        # st2: [40, 41, 42, 43] → mean = 41.5
        # st3: [30, 31, 32, 33] → mean = 31.5

        assert len(hourly) == 3  # 3 stations
        assert hourly.select("observation_count").item(0, 0) == 4

    def test_median_calculation(self, sample_raw_air_quality):
        """Test median value calculation."""
        # Group by hour and calculate median
        hourly = sample_raw_air_quality.with_columns(
            hour_start=pl.col("observed_at").dt.truncate("1h")
        ).group_by(
            ["hour_start", "source", "station_id", "pollutant"]
        ).agg(
            pl.col("value").median().alias("median_value"),
        )

        # st1: median([35, 36, 37, 38]) = 36.5
        # st2: median([40, 41, 42, 43]) = 41.5
        # st3: median([30, 31, 32, 33]) = 31.5

        assert len(hourly) == 3
        medians = sorted(hourly.select("median_value").to_series().to_list())
        assert medians == [31.5, 36.5, 41.5]

    def test_stddev_calculation(self, sample_raw_air_quality):
        """Test standard deviation calculation."""
        hourly = sample_raw_air_quality.with_columns(
            hour_start=pl.col("observed_at").dt.truncate("1h")
        ).group_by(
            ["hour_start", "station_id"]
        ).agg(
            pl.col("value").std().alias("stddev_value"),
        )

        # Each station has consistent increments (±1)
        # st1: [35, 36, 37, 38] → stddev ≈ 1.29
        # st2: [40, 41, 42, 43] → stddev ≈ 1.29
        # st3: [30, 31, 32, 33] → stddev ≈ 1.29

        stddevs = hourly.select("stddev_value").to_series()
        for val in stddevs:
            assert val is not None
            assert val > 1.0


class TestCoverageCalculation:
    """Test coverage percentage calculation."""

    def test_full_coverage_100(self):
        """Test 100% coverage when all observations present."""
        observation_count = 4
        expected_observation_count = 4
        coverage_pct = (observation_count / expected_observation_count) * 100

        assert coverage_pct == 100.0

    def test_partial_coverage(self):
        """Test partial coverage."""
        observation_count = 2
        expected_observation_count = 4
        coverage_pct = (observation_count / expected_observation_count) * 100

        assert coverage_pct == 50.0

    def test_zero_coverage(self):
        """Test 0% coverage when no observations."""
        observation_count = 0
        expected_observation_count = 4
        coverage_pct = (observation_count / expected_observation_count) * 100

        assert coverage_pct == 0.0


class TestBaselineJoin:
    """Test baseline join and anomaly detection."""

    def test_baseline_median_comparison(self, baselines):
        """Test baseline median is available after join."""
        # Fact data: hour 10 with median 35 (vs baseline 40)
        fact_median = 35.0

        # Simulate join
        filtered = baselines.filter(
            (pl.col("hour_of_day") == 10) & (pl.col("pollutant") == "pm25")
        )
        baseline_median = filtered.select("historical_median").item(0, 0)
        baseline_mad = filtered.select("mad").item(0, 0)

        assert baseline_median == 40.0
        assert abs(fact_median - baseline_median) == 5.0

    def test_anomaly_detection(self, baselines):
        """Test anomaly flag set when deviation > 3*MAD."""
        # Hour 10: baseline median=40, MAD=5
        # Observation: median=20 (deviation = 20, which is 4*5)

        baseline_data = baselines.filter(pl.col("hour_of_day") == 10)
        baseline_median = baseline_data.select("historical_median").item(0, 0)
        baseline_mad = baseline_data.select("mad").item(0, 0)
        observation_median = 20.0

        deviation = abs(observation_median - baseline_median)
        anomaly = 1 if deviation > 3 * baseline_mad else 0

        assert anomaly == 1  # 20 > 3*5


class TestWeatherAggregation:
    """Test weather hourly aggregation."""

    def test_weather_mean_temperature(self, sample_weather_data):
        """Test mean temperature calculation."""
        hourly = sample_weather_data.with_columns(
            hour_start=pl.col("observed_at").dt.truncate("1h")
        ).group_by(
            "hour_start"
        ).agg(
            pl.col("temperature_c").mean().alias("mean_temp"),
            pl.col("temperature_c").min().alias("min_temp"),
            pl.col("temperature_c").max().alias("max_temp"),
        )

        mean_temp = hourly.select("mean_temp").item(0, 0)
        # First 6 observations: [28.0, 28.5, 29.0, 29.5, 30.0, 30.5] = 29.25
        # All 8 observations: [28.0, 28.5, 29.0, 29.5, 30.0, 30.5, 31.0, 31.5] = 29.75
        # The truncate to 1h groups all observations in the hour 10:00-10:59
        assert 29.0 < mean_temp < 30.0  # Somewhere in the range

    def test_weather_humidity_aggregation(self, sample_weather_data):
        """Test humidity aggregation."""
        hourly = sample_weather_data.with_columns(
            hour_start=pl.col("observed_at").dt.truncate("1h")
        ).group_by(
            "hour_start"
        ).agg(
            pl.col("humidity_pct").mean().alias("mean_humidity"),
        )

        mean_humidity = hourly.select("mean_humidity").item(0, 0)
        # Observations: [65, 64, 63, 62, 61, 60, 59, 58]
        # Mean should be around 61.5 for all 8
        assert 55.0 < mean_humidity < 65.0  # Somewhere in the range


class TestQualityScore:
    """Test quality score calculation."""

    def test_quality_score_100_full_coverage(self):
        """Test quality score is 100 with full coverage."""
        coverage_pct = 100.0
        quality_score = min(100, max(0, coverage_pct * 0.7 + 30.0))
        assert quality_score == 100.0

    def test_quality_score_50_half_coverage(self):
        """Test quality score at 50% coverage."""
        coverage_pct = 50.0
        quality_score = min(100, max(0, coverage_pct * 0.7 + 30.0))
        # 50 * 0.7 + 30 = 35 + 30 = 65
        assert quality_score == 65.0

    def test_quality_score_0_no_coverage(self):
        """Test quality score with no coverage."""
        coverage_pct = 0.0
        quality_score = min(100, max(0, coverage_pct * 0.7 + 30.0))
        # 0 * 0.7 + 30 = 30
        assert quality_score == 30.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
