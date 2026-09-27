"""Unit tests for BaselineCalculator in aq_engine.analytics.baselines."""

from datetime import UTC, date, datetime
from unittest.mock import patch

import polars as pl
import pytest
from aq_engine.analytics.baselines import BaselineCalculator


@pytest.fixture
def temp_dirs(tmp_path):
    storage = tmp_path / "raw"
    marts = tmp_path / "marts"
    storage.mkdir()
    marts.mkdir()
    return storage, marts


@pytest.fixture
def calculator(temp_dirs):
    storage, marts = temp_dirs
    return BaselineCalculator(storage_root=str(storage), marts_root=str(marts))


class TestBaselineCalculatorMath:
    """Test percentile and MAD calculation helpers."""

    def test_percentile_empty(self):
        assert BaselineCalculator._percentile([], 0.5) is None

    def test_percentile_single(self):
        assert BaselineCalculator._percentile([42.0], 0.5) == 42.0

    def test_percentile_interpolation(self):
        values = [10.0, 20.0, 30.0, 40.0]
        # p50
        assert BaselineCalculator._percentile(values, 0.5) == 25.0
        # p0
        assert BaselineCalculator._percentile(values, 0.0) == 10.0
        # p100
        assert BaselineCalculator._percentile(values, 1.0) == 40.0

    def test_mad_empty(self):
        assert BaselineCalculator._mad([], 10.0) is None

    def test_mad_values(self):
        values = [10.0, 20.0, 30.0]
        median = 20.0
        # deviations: [10, 0, 10] -> sorted [0, 10, 10] -> median is 10.0
        assert BaselineCalculator._mad(values, median) == 10.0


class TestBaselineComputation:
    """Test hourly and monthly baseline computation."""

    def test_compute_hourly_baselines_empty_records(self, calculator):
        df = calculator.compute_hourly_baselines(
            location_id="loc_1",
            pollutant="pm25",
            current_date=date(2026, 8, 15),
        )
        assert df.is_empty()

    def test_compute_hourly_baselines_with_data(self, calculator):
        # Generate 70 observations for month=8, hour=12 to exceed MIN_OBSERVATIONS (60)
        records = [
            {
                "observed_at": datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
                "value": 50.0 + (i % 10),
            }
            for i in range(70)
        ]

        with patch.object(calculator, "_read_raw_data", return_value=records):
            df = calculator.compute_hourly_baselines(
                location_id="loc_1",
                pollutant="pm25",
                current_date=date(2026, 8, 15),
            )

        assert not df.is_empty()
        assert "median" in df.columns
        assert "mad" in df.columns
        row = df.to_dicts()[0]
        assert row["observation_count"] == 70
        assert row["fallback_used"] is False

    def test_compute_hourly_baselines_fallback(self, calculator):
        # Only 10 observations -> triggers fallback
        records = [
            {
                "observed_at": datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
                "value": 50.0,
            }
            for _ in range(10)
        ]

        with patch.object(calculator, "_read_raw_data", return_value=records):
            df = calculator.compute_hourly_baselines(
                location_id="loc_1",
                pollutant="pm25",
                current_date=date(2026, 8, 15),
            )

        assert not df.is_empty()
        row = df.to_dicts()[0]
        assert row["fallback_used"] is True

    def test_compute_monthly_baselines(self, calculator):
        records = [
            {
                "observed_at": datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
                "value": 45.0 + i,
            }
            for i in range(65)
        ]

        with patch.object(calculator, "_read_raw_data", return_value=records):
            df = calculator.compute_monthly_baselines(
                location_id="loc_1",
                pollutant="pm25",
                current_date=date(2026, 8, 15),
            )

        assert not df.is_empty()
        row = df.to_dicts()[0]
        assert row["month"] == 8
        assert row["hour_of_day"] is None

    def test_save_and_get_baseline(self, calculator, temp_dirs):
        _, marts = temp_dirs
        df = pl.DataFrame({
            "location_id": ["loc_1"],
            "pollutant": ["pm25"],
            "month": [8],
            "hour_of_day": [10],
            "median": [55.0],
        })

        saved_path = calculator.save_baselines(df, location_id="loc_1", version="v1")
        assert saved_path.exists()
        assert calculator.get_baseline("loc_1", "pm25", 8, 10) is None
        assert calculator._read_raw_data("loc_1", "pm25", date(2026, 1, 1), date(2026, 1, 2)) == []
