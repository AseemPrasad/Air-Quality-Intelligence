
"""Unit tests for BaselineCalculator in aq_engine.analytics.baselines."""

from datetime import UTC, date, datetime
from unittest.mock import patch

import polars as pl
import pytest

from aq_engine.analytics.baselines import BaselineCalculator


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary storage directories."""
    storage = tmp_path / "raw"
    marts = tmp_path / "marts"
    storage.mkdir()
    marts.mkdir()
    return storage, marts


@pytest.fixture
def calculator(temp_dirs):
    """Create a baseline calculator."""
    storage, marts = temp_dirs
    return BaselineCalculator(
        storage_root=str(storage),
        marts_root=str(marts),
    )


class TestBaselineCalculatorMath:
    """Test percentile and MAD calculation helpers."""

    def test_percentile_empty(self):
        assert BaselineCalculator._percentile([], 0.5) is None

    def test_percentile_single(self):
        assert BaselineCalculator._percentile([42.0], 0.5) == 42.0

    def test_percentile_interpolation(self):
        values = [10.0, 20.0, 30.0, 40.0]

        assert BaselineCalculator._percentile(values, 0.5) == 25.0
        assert BaselineCalculator._percentile(values, 0.0) == 10.0
        assert BaselineCalculator._percentile(values, 1.0) == 40.0

    def test_mad_empty(self):
        assert BaselineCalculator._mad([], 10.0) is None

    def test_mad_values(self):
        values = [10.0, 20.0, 30.0]
        median = 20.0

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
        """Test hourly baseline computation with sufficient observations."""
        records = [
            {
                "observed_at": datetime(
                    2026, 8, 15, 12, 0, tzinfo=UTC
                ),
                "value": 50.0 + (i % 10),
            }
            for i in range(70)
        ]

        with patch.object(
            calculator,
            "_read_raw_data",
            return_value=records,
        ):
            df = calculator.compute_hourly_baselines(
                location_id="loc_1",
                pollutant="pm25",
                current_date=date(2026, 8, 15),
            )

        assert not df.is_empty()
        assert "median" in df.columns
        assert "mad" in df.columns
        assert "p50" in df.columns
        assert "p75" in df.columns
        assert "p90" in df.columns

        row = df.to_dicts()[0]

        assert row["observation_count"] == 70
        assert row["median"] == 54.5
        assert row["fallback_used"] is False

    def test_compute_hourly_baselines_fallback(self, calculator):
        """Test fallback when observations are insufficient."""
        records = [
            {
                "observed_at": datetime(
                    2026, 8, 15, 12, 0, tzinfo=UTC
                ),
                "value": 50.0,
            }
            for _ in range(10)
        ]

        with patch.object(
            calculator,
            "_read_raw_data",
            return_value=records,
        ):
            df = calculator.compute_hourly_baselines(
                location_id="loc_1",
                pollutant="pm25",
                current_date=date(2026, 8, 15),
            )

        assert not df.is_empty()

        row = df.to_dicts()[0]

        assert row["fallback_used"] is True
        assert row["fallback_reason"] == "citywide_fallback"
        assert row["observation_count"] == 1

    def test_compute_monthly_baselines(self, calculator):
        """Test monthly baseline computation."""
        records = [
            {
                "observed_at": datetime(
                    2026, 8, 15, 12, 0, tzinfo=UTC
                ),
                "value": 45.0 + i,
            }
            for i in range(65)
        ]

        with patch.object(
            calculator,
            "_read_raw_data",
            return_value=records,
        ):
            df = calculator.compute_monthly_baselines(
                location_id="loc_1",
                pollutant="pm25",
                current_date=date(2026, 8, 15),
            )

        assert not df.is_empty()

        row = df.to_dicts()[0]

        assert row["month"] == 8
        assert row["hour_of_day"] is None
        assert row["observation_count"] == 65
        assert row["fallback_used"] is False

    def test_save_and_get_baseline(self, calculator, temp_dirs):
        """Test baseline saving and current retrieval behavior."""
        _, marts = temp_dirs

        df = pl.DataFrame(
            {
                "location_id": ["loc_1"],
                "pollutant": ["pm25"],
                "month": [8],
                "hour_of_day": [10],
                "median": [55.0],
            }
        )

        saved_path = calculator.save_baselines(
            df,
            location_id="loc_1",
            version="v1",
        )

        assert saved_path.exists()
        assert saved_path.parent == marts / "hourly_baselines" / "loc_1"

        loaded_df = pl.read_parquet(saved_path)

        assert loaded_df.height == 1
        assert loaded_df["median"][0] == 55.0
        assert loaded_df["pollutant"][0] == "pm25"

        # get_baseline currently returns None in the production
        # implementation because Parquet retrieval is not implemented.
        assert calculator.get_baseline(
            "loc_1", "pm25", 8, 10
        ) is None


class TestBaselineEdgeCases:
    """Test edge cases in baseline calculations."""

    def test_empty_baseline_row(self):
        row = BaselineCalculator._empty_baseline_row(
            location_id="loc_1",
            pollutant="pm25",
            month=8,
            hour_of_day=12,
            fallback_reason="no_data",
        )

        assert row["location_id"] == "loc_1"
        assert row["pollutant"] == "pm25"
        assert row["observation_count"] == 0
        assert row["median"] is None
        assert row["mad"] is None
        assert row["fallback_used"] is True
        assert row["fallback_reason"] == "no_data"

    def test_percentile_ordering(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]

        p25 = BaselineCalculator._percentile(values, 0.25)
        p50 = BaselineCalculator._percentile(values, 0.50)
        p75 = BaselineCalculator._percentile(values, 0.75)

        assert p25 <= p50 <= p75

    def test_mad_zero_deviation(self):
        values = [25.0, 25.0, 25.0]

        result = BaselineCalculator._mad(values, 25.0)

        assert result == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
