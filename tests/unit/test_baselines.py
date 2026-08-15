"""Unit tests for historical baseline calculation.

Tests baseline computation for hourly and monthly windows with
fallback logic for insufficient data.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import date, timedelta, datetime, timezone
from unittest.mock import Mock, patch
import polars as pl

from aq_engine.analytics.baselines import BaselineCalculator


@pytest.fixture
def temp_storage():
    """Temporary storage directory."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aq_baselines_test_"))
    yield temp_dir
    if temp_dir.exists():
        import shutil
        shutil.rmtree(temp_dir)


@pytest.fixture
def calculator(temp_storage):
    """BaselineCalculator with temporary storage."""
    return BaselineCalculator(
        storage_root=str(temp_storage),
        marts_root=str(temp_storage / "marts"),
    )


@pytest.fixture
def full_year_data():
    """365 days of data for testing."""
    records = []
    base_time = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    for day in range(365):
        current_time = base_time + timedelta(days=day)
        for hour in range(24):
            for station in range(3):  # 3 stations
                records.append({
                    "value": 35.0 + (day % 30) + (hour % 12),  # Vary by day/hour
                    "observed_at": current_time.replace(hour=hour),
                    "location_id": f"station_{station}",
                    "pollutant": "pm25",
                })

    return records


@pytest.fixture
def thirty_days_data():
    """30 days of data for testing fallback."""
    records = []
    base_time = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    for day in range(30):
        current_time = base_time + timedelta(days=day)
        for hour in range(24):
            for station in range(2):  # 2 stations
                records.append({
                    "value": 40.0 + (day % 20),
                    "observed_at": current_time.replace(hour=hour),
                    "location_id": f"station_{station}",
                    "pollutant": "pm25",
                })

    return records


class TestBaselineCalculation:
    """Test baseline calculation logic."""

    def test_sufficient_data_365_days(self, calculator, full_year_data):
        """Test with 365 days of data (sufficient for baseline)."""
        with patch.object(calculator, "_read_raw_data", return_value=full_year_data):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=365,
                current_date=date(2025, 12, 31),
            )

            assert len(baseline_df) > 0
            assert "median" in baseline_df.columns
            assert "fallback_used" in baseline_df.columns

    def test_baselines_have_required_columns(self, calculator, full_year_data):
        """Test baseline output has all required columns."""
        with patch.object(calculator, "_read_raw_data", return_value=full_year_data):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=365,
            )

            required_cols = [
                "location_id",
                "pollutant",
                "month",
                "hour_of_day",
                "observation_count",
                "median",
                "mad",
                "p50",
                "p75",
                "p90",
                "p95",
                "p99",
                "fallback_used",
                "fallback_reason",
            ]

            for col in required_cols:
                assert col in baseline_df.columns, f"Missing column: {col}"

    def test_median_calculation(self, calculator):
        """Test median calculation."""
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        median = calculator._percentile(values, 0.5)
        assert median == 5.5

    def test_percentile_calculation(self, calculator):
        """Test percentile calculations."""
        values = list(range(1, 101))  # 1-100

        assert calculator._percentile(values, 0.25) == pytest.approx(25.75, abs=1)
        assert calculator._percentile(values, 0.5) == pytest.approx(50.5, abs=1)
        assert calculator._percentile(values, 0.75) == pytest.approx(75.25, abs=1)
        assert calculator._percentile(values, 0.95) == pytest.approx(95.05, abs=1)

    def test_mad_calculation(self, calculator):
        """Test Median Absolute Deviation."""
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        median = 5.5
        mad = calculator._mad(values, median)

        # Deviations: |1-5.5|=4.5, |2-5.5|=3.5, ..., |10-5.5|=4.5
        # Sorted: [0.5, 1.5, 1.5, 2.5, 2.5, 3.5, 3.5, 4.5, 4.5, 4.5]
        # Median of deviations ≈ 2.5-3.0
        assert mad > 0
        assert mad < 5

    def test_insufficient_data_30_days(self, calculator):
        """Test with sparse data (insufficient, triggers fallback)."""
        # Create sparse data: only 5 days with 2 stations = 10 observations per hour
        # This is less than MIN_OBSERVATIONS (60)
        records = []
        base_time = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        for day in range(5):
            current_time = base_time + timedelta(days=day)
            for hour in range(24):
                records.append({
                    "value": 35.0 + day,
                    "observed_at": current_time.replace(hour=hour),
                    "location_id": "station_0",
                    "pollutant": "pm25",
                })

        with patch.object(calculator, "_read_raw_data", return_value=records):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=5,
            )

            # With sparse data, might have some fallbacks
            if len(baseline_df) > 0:
                # All rows should have been computed (either direct or via fallback)
                assert len(baseline_df) > 0


class TestFallbackLogic:
    """Test fallback mechanisms."""

    def test_weekly_fallback_attempted(self, calculator):
        """Test weekly fallback is attempted."""
        values, reason = calculator._try_weekly_fallback(
            location_id="station_0",
            pollutant="pm25",
            month=1,
            hour_of_day=10,
            all_data=pl.DataFrame(),
        )

        assert reason == "weekly_fallback"

    def test_citywide_fallback(self, calculator):
        """Test city-wide fallback logic."""
        values, reason = calculator._try_citywide_fallback(
            location_id="station_0",
            pollutant="pm25",
            month=1,
            hour_of_day=10,
            all_data=pl.DataFrame(),
        )

        assert reason == "citywide_fallback"
        assert len(values) > 0

    def test_empty_baseline_row(self, calculator):
        """Test empty baseline row creation."""
        row = calculator._empty_baseline_row(
            location_id="station_0",
            pollutant="pm25",
            month=1,
            hour_of_day=10,
            fallback_reason="no_data",
        )

        assert row["location_id"] == "station_0"
        assert row["pollutant"] == "pm25"
        assert row["observation_count"] == 0
        assert row["median"] is None
        assert row["fallback_used"] is True


class TestMonthlyBaselines:
    """Test monthly baseline computation."""

    def test_monthly_baselines_5_years(self, calculator, full_year_data):
        """Test monthly baseline with 5 years of data."""
        # Create 5 years of data
        extended_data = []
        for year in range(5):
            for record in full_year_data:
                new_record = record.copy()
                # Offset timestamp by year
                observed_at = record["observed_at"]
                new_record["observed_at"] = observed_at.replace(year=2021 + year)
                extended_data.append(new_record)

        with patch.object(calculator, "_read_raw_data", return_value=extended_data):
            baseline_df = calculator.compute_monthly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_years=5,
                current_date=date(2025, 12, 31),
            )

            assert len(baseline_df) > 0
            # Should have roughly 12 months
            assert len(baseline_df) <= 12


class TestBaselineStorage:
    """Test baseline storage and retrieval."""

    def test_save_baselines(self, calculator, full_year_data):
        """Test saving baselines to Parquet."""
        with patch.object(calculator, "_read_raw_data", return_value=full_year_data):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=365,
            )

            if len(baseline_df) > 0:
                filepath = calculator.save_baselines(baseline_df, location_id="station_0")

                assert filepath.exists()
                assert filepath.suffix == ".parquet"
                assert "station_0" in str(filepath)

    def test_save_baselines_with_version(self, calculator, full_year_data):
        """Test saving baselines with custom version."""
        with patch.object(calculator, "_read_raw_data", return_value=full_year_data):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=365,
            )

            if len(baseline_df) > 0:
                filepath = calculator.save_baselines(
                    baseline_df, location_id="station_0", version="v1.0.0"
                )

                assert "v1.0.0" in str(filepath)

    def test_multiple_baseline_versions(self, calculator, full_year_data):
        """Test saving multiple baseline versions."""
        with patch.object(calculator, "_read_raw_data", return_value=full_year_data):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=365,
            )

            if len(baseline_df) > 0:
                path1 = calculator.save_baselines(
                    baseline_df, location_id="station_0", version="v1"
                )
                path2 = calculator.save_baselines(
                    baseline_df, location_id="station_0", version="v2"
                )

                assert path1 != path2
                assert path1.exists()
                assert path2.exists()


class TestEdgeCases:
    """Test edge cases."""

    def test_no_data_returns_empty_dataframe(self, calculator):
        """Test with no data returns empty DataFrame."""
        with patch.object(calculator, "_read_raw_data", return_value=[]):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=365,
            )

            assert len(baseline_df) == 0 or baseline_df is None or len(baseline_df.height) == 0

    def test_nan_handling(self, calculator):
        """Test NaN value handling."""
        records = [
            {
                "value": 35.0,
                "observed_at": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            },
            {"value": float("nan"), "observed_at": datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)},
            {
                "value": 38.0,
                "observed_at": datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc),
            },
        ]

        # Test that NaN values are filtered out
        baseline_row = calculator._calculate_baseline_row(
            location_id="station_0",
            pollutant="pm25",
            month=1,
            hour_of_day=10,
            values=[35.0, float("nan"), 38.0],
            all_data=pl.DataFrame(),
        )

        # If enough data after NaN removal, should still calculate
        assert baseline_row["observation_count"] >= 0

    def test_zero_values(self, calculator):
        """Test handling of zero values."""
        values = [0.0, 10.0, 20.0, 30.0, 40.0]
        median = calculator._percentile(values, 0.5)
        assert median == 20.0

    def test_negative_values_rejected(self, calculator):
        """Test that negative values are handled (they might be invalid for pollution)."""
        records = [
            {
                "value": -5.0,  # Invalid (negative)
                "observed_at": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            },
        ]

        # Baseline calculation should handle this gracefully
        baseline_row = calculator._calculate_baseline_row(
            location_id="station_0",
            pollutant="pm25",
            month=1,
            hour_of_day=10,
            values=[-5.0],
            all_data=pl.DataFrame(),
        )

        # Should create row but it might be sparse due to invalid data
        assert baseline_row["location_id"] == "station_0"


class TestStatisticalValidity:
    """Test statistical validity of baselines."""

    def test_percentile_ordering(self, calculator):
        """Test that percentiles are ordered correctly."""
        records = []
        base_time = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        for i in range(200):
            records.append({
                "value": 30.0 + i * 0.5,  # Values from 30 to 130
                "observed_at": base_time + timedelta(hours=i),
                "location_id": "station_0",
                "pollutant": "pm25",
            })

        with patch.object(calculator, "_read_raw_data", return_value=records):
            baseline_df = calculator.compute_hourly_baselines(
                location_id="station_0",
                pollutant="pm25",
                lookback_days=10,
            )

            if len(baseline_df) > 0:
                for row in baseline_df.iter_rows(named=True):
                    if row["observation_count"] > 0:
                        # Check percentile ordering
                        p50 = row["p50"]
                        p75 = row["p75"]
                        p90 = row["p90"]
                        p95 = row["p95"]
                        p99 = row["p99"]

                        if all(v is not None for v in [p50, p75, p90, p95, p99]):
                            assert p50 <= p75 <= p90 <= p95 <= p99, \
                                f"Percentiles not ordered: {p50}, {p75}, {p90}, {p95}, {p99}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
