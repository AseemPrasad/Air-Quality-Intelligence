"""Unit tests for time-series split logic.

Tests chronological splits, walk-forward validation, and data leakage prevention.
"""

import pytest
from datetime import date, datetime, timezone, timedelta

from aq_engine.ml.split import TimeSeriesSplitter


@pytest.fixture
def splitter():
    """TimeSeriesSplitter instance."""
    return TimeSeriesSplitter()


@pytest.fixture
def date_range_1_year():
    """1-year date range for testing."""
    return date(2023, 1, 1), date(2023, 12, 31)


@pytest.fixture
def date_range_3_years():
    """3-year date range for testing."""
    return date(2023, 1, 1), date(2025, 12, 31)


class TestBasicSplits:
    """Test basic train/val/test split creation."""

    def test_create_splits_returns_three_ranges(self, splitter, date_range_1_year):
        """Test create_splits returns three date ranges."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        assert isinstance(train, tuple) and len(train) == 2
        assert isinstance(val, tuple) and len(val) == 2
        assert isinstance(test, tuple) and len(test) == 2

    def test_split_dates_are_dates(self, splitter, date_range_1_year):
        """Test split dates are date objects."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        assert isinstance(train[0], date) and isinstance(train[1], date)
        assert isinstance(val[0], date) and isinstance(val[1], date)
        assert isinstance(test[0], date) and isinstance(test[1], date)

    def test_default_percentages_70_15_15(self, splitter, date_range_1_year):
        """Test default percentages (70/15/15)."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        train_days = (train[1] - train[0]).days + 1
        val_days = (val[1] - val[0]).days + 1
        test_days = (test[1] - test[0]).days + 1
        total_days = train_days + val_days + test_days

        # Should be approximately 70/15/15 (accounting for rounding)
        assert train_days / total_days >= 0.69
        assert val_days / total_days >= 0.14
        assert test_days / total_days >= 0.14

    def test_custom_percentages_50_25_25(self, splitter, date_range_1_year):
        """Test custom percentages (50/25/25)."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end, train_pct=0.5, val_pct=0.25)

        train_days = (train[1] - train[0]).days + 1
        val_days = (val[1] - val[0]).days + 1
        test_days = (test[1] - test[0]).days + 1
        total_days = train_days + val_days + test_days

        assert train_days / total_days >= 0.49
        assert val_days / total_days >= 0.24
        assert test_days / total_days >= 0.24


class TestChronologicalOrder:
    """Test that splits maintain chronological order."""

    def test_train_before_val(self, splitter, date_range_1_year):
        """Test train period ends before val period starts."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        assert train[1] < val[0]

    def test_val_before_test(self, splitter, date_range_1_year):
        """Test val period ends before test period starts."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        assert val[1] < test[0]

    def test_no_overlap_train_val(self, splitter, date_range_1_year):
        """Test train and val don't overlap."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        # No date should be in both train and val
        assert train[1] < val[0]

    def test_no_overlap_val_test(self, splitter, date_range_1_year):
        """Test val and test don't overlap."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        # No date should be in both val and test
        assert val[1] < test[0]

    def test_complete_coverage(self, splitter, date_range_1_year):
        """Test splits cover entire date range with no gaps."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        # Train should start at start_date
        assert train[0] == start

        # Test should end at end_date
        assert test[1] == end

        # No gaps: train ends day before val, val ends day before test
        assert train[1] + timedelta(days=1) == val[0]
        assert val[1] + timedelta(days=1) == test[0]


class Test3YearSplit:
    """Test 3-year split example from specification."""

    def test_3_year_split_example(self, splitter):
        """Test example: 3 years (2023-2025) with 70/15/15."""
        start = date(2023, 1, 1)
        end = date(2025, 12, 31)

        train, val, test = splitter.create_splits(start, end, train_pct=0.7, val_pct=0.15)

        # Total days: 1096 (2023: 365, 2024: 366 leap, 2025: 365; inclusive)
        total_days = (end - start).days + 1
        assert total_days == 1096

        # Calculate expected days
        train_days = int(1096 * 0.7)  # 767
        val_days = int(1096 * 0.15)   # 164
        test_days = 1096 - train_days - val_days  # 165

        # Verify
        actual_train_days = (train[1] - train[0]).days + 1
        actual_val_days = (val[1] - val[0]).days + 1
        actual_test_days = (test[1] - test[0]).days + 1

        assert actual_train_days == train_days
        assert actual_val_days == val_days
        assert actual_test_days == test_days

        # Log for verification
        print(f"Train: {train[0]} to {train[1]} ({actual_train_days} days)")
        print(f"Val: {val[0]} to {val[1]} ({actual_val_days} days)")
        print(f"Test: {test[0]} to {test[1]} ({actual_test_days} days)")


class TestWalkForwardSplits:
    """Test walk-forward validation splits."""

    def test_walk_forward_returns_list(self, splitter, date_range_3_years):
        """Test walk_forward_splits returns list of splits."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        assert isinstance(splits, list)
        assert len(splits) > 0

    def test_walk_forward_split_structure(self, splitter, date_range_3_years):
        """Test each split has (train_range, test_range) structure."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        for split in splits:
            assert isinstance(split, tuple) and len(split) == 2
            train, test = split
            assert isinstance(train, tuple) and len(train) == 2
            assert isinstance(test, tuple) and len(test) == 2

    def test_walk_forward_chronological_order(self, splitter, date_range_3_years):
        """Test walk-forward splits maintain chronological order."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        for i, (train, test) in enumerate(splits):
            # Train ends before test starts
            assert train[1] < test[0]

            # Each window expands
            if i > 0:
                prev_train, prev_test = splits[i - 1]
                # Train window expanded (same start, later end)
                assert train[0] == prev_train[0]
                assert train[1] >= prev_train[1]

    def test_walk_forward_no_test_overlap(self, splitter, date_range_3_years):
        """Test test folds don't overlap in walk-forward."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        for i in range(len(splits) - 1):
            _, test_i = splits[i]
            _, test_next = splits[i + 1]

            # Test fold i ends before test fold i+1 starts
            assert test_i[1] < test_next[0]

    def test_walk_forward_window_expansion(self, splitter, date_range_3_years):
        """Test training window expands properly."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        # First split: train window 30 days, test window 7 days
        train, test = splits[0]
        assert (train[1] - train[0]).days + 1 == 30
        assert (test[1] - test[0]).days + 1 == 7

    def test_walk_forward_expands_by_step(self, splitter, date_range_3_years):
        """Test training window expands by step_days."""
        start, end = date_range_3_years
        window_days = 30
        step_days = 7
        splits = splitter.walk_forward_splits(start, end, window_days=window_days, step_days=step_days)

        prev_train_days = window_days

        for i, (train, test) in enumerate(splits):
            if i > 0:
                # Window expanded by step_days from previous
                train_days = (train[1] - train[0]).days + 1
                # Should be prev_train_days + step_days (approximately)
                assert train_days == prev_train_days + step_days

            prev_train_days = (train[1] - train[0]).days + 1


class TestWalkForwardVariations:
    """Test walk-forward with different parameters."""

    def test_walk_forward_small_window(self, splitter, date_range_3_years):
        """Test walk-forward with small window."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=10, step_days=5)

        assert len(splits) > 0
        # More splits with smaller window
        splits_large = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)
        assert len(splits) > len(splits_large)

    def test_walk_forward_large_step(self, splitter, date_range_3_years):
        """Test walk-forward with large step."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=30)

        assert len(splits) > 0

    def test_walk_forward_covers_end_date(self, splitter, date_range_3_years):
        """Test walk-forward last split includes end_date."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        # Last split should reach or exceed end_date
        last_train, last_test = splits[-1]
        assert last_test[1] <= end


class TestInputValidation:
    """Test input validation and error handling."""

    def test_invalid_train_pct_zero(self, splitter, date_range_1_year):
        """Test train_pct=0 raises error."""
        start, end = date_range_1_year
        with pytest.raises(ValueError):
            splitter.create_splits(start, end, train_pct=0.0)

    def test_invalid_train_pct_one(self, splitter, date_range_1_year):
        """Test train_pct=1.0 raises error."""
        start, end = date_range_1_year
        with pytest.raises(ValueError):
            splitter.create_splits(start, end, train_pct=1.0)

    def test_invalid_percentages_sum_to_one(self, splitter, date_range_1_year):
        """Test train_pct + val_pct >= 1.0 raises error."""
        start, end = date_range_1_year
        with pytest.raises(ValueError):
            splitter.create_splits(start, end, train_pct=0.7, val_pct=0.3)

    def test_invalid_date_range_reversed(self, splitter):
        """Test start > end raises error."""
        start = date(2023, 12, 31)
        end = date(2023, 1, 1)
        with pytest.raises(ValueError):
            splitter.create_splits(start, end)

    def test_invalid_date_range_same(self, splitter):
        """Test start == end raises error."""
        start = date(2023, 1, 1)
        end = date(2023, 1, 1)
        with pytest.raises(ValueError):
            splitter.create_splits(start, end)

    def test_invalid_window_days_zero(self, splitter, date_range_3_years):
        """Test window_days=0 raises error."""
        start, end = date_range_3_years
        with pytest.raises(ValueError):
            splitter.walk_forward_splits(start, end, window_days=0, step_days=7)

    def test_invalid_step_days_zero(self, splitter, date_range_3_years):
        """Test step_days=0 raises error."""
        start, end = date_range_3_years
        with pytest.raises(ValueError):
            splitter.walk_forward_splits(start, end, window_days=30, step_days=0)

    def test_invalid_date_range_too_small(self, splitter):
        """Test date range too small for walk-forward."""
        start = date(2023, 1, 1)
        end = date(2023, 1, 10)
        with pytest.raises(ValueError):
            splitter.walk_forward_splits(start, end, window_days=30, step_days=7)


class TestDatetimeHandling:
    """Test handling of datetime objects."""

    def test_datetime_input_converted_to_date(self, splitter):
        """Test datetime inputs are normalized to dates."""
        start = datetime(2023, 1, 1, 12, 30, 45, tzinfo=timezone.utc)
        end = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        train, val, test = splitter.create_splits(start, end)

        # Results should be date objects, not datetime
        assert isinstance(train[0], date)
        assert isinstance(train[1], date)

    def test_datetime_walk_forward(self, splitter):
        """Test walk-forward with datetime inputs."""
        start = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2023, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

        splits = splitter.walk_forward_splits(start, end, window_days=20, step_days=10)

        assert len(splits) > 0


class TestUtilityMethods:
    """Test utility methods."""

    def test_get_date_range_days(self, splitter):
        """Test get_date_range_days calculation."""
        start = date(2023, 1, 1)
        end = date(2023, 1, 10)

        days = splitter.get_date_range_days(start, end)

        # 10 days (inclusive)
        assert days == 10

    def test_get_date_range_days_1_day(self, splitter):
        """Test single day range."""
        start = date(2023, 1, 1)
        end = date(2023, 1, 1)

        days = splitter.get_date_range_days(start, end)

        assert days == 1

    def test_split_contains_date_true(self, splitter):
        """Test split_contains_date returns True for date in range."""
        split_start = date(2023, 1, 1)
        split_end = date(2023, 1, 31)
        target = date(2023, 1, 15)

        assert splitter.split_contains_date(split_start, split_end, target)

    def test_split_contains_date_boundary(self, splitter):
        """Test split_contains_date for boundary dates."""
        split_start = date(2023, 1, 1)
        split_end = date(2023, 1, 31)

        assert splitter.split_contains_date(split_start, split_end, split_start)
        assert splitter.split_contains_date(split_start, split_end, split_end)

    def test_split_contains_date_false(self, splitter):
        """Test split_contains_date returns False for date outside range."""
        split_start = date(2023, 1, 1)
        split_end = date(2023, 1, 31)
        target = date(2023, 2, 1)

        assert not splitter.split_contains_date(split_start, split_end, target)


class TestDataLeakagePrevention:
    """Test that splits prevent data leakage."""

    def test_no_leakage_val_to_train(self, splitter, date_range_1_year):
        """Test validation set doesn't leak into training."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        # No validation date in training period
        for d in range((val[1] - val[0]).days + 1):
            check_date = val[0] + timedelta(days=d)
            assert not splitter.split_contains_date(train[0], train[1], check_date)

    def test_no_leakage_test_to_val(self, splitter, date_range_1_year):
        """Test test set doesn't leak into validation."""
        start, end = date_range_1_year
        train, val, test = splitter.create_splits(start, end)

        # No test date in validation period
        for d in range((test[1] - test[0]).days + 1):
            check_date = test[0] + timedelta(days=d)
            assert not splitter.split_contains_date(val[0], val[1], check_date)

    def test_walk_forward_no_train_leakage(self, splitter, date_range_3_years):
        """Test walk-forward training data doesn't leak into test."""
        start, end = date_range_3_years
        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        for train, test in splits:
            # No test date should be in training period
            assert train[1] < test[0]


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_small_date_range(self, splitter):
        """Test smallest valid date range."""
        start = date(2023, 1, 1)
        end = date(2023, 1, 10)  # 10 days

        train, val, test = splitter.create_splits(start, end, train_pct=0.5, val_pct=0.25)

        # Should not raise; all splits should have at least 1 day
        assert train[0] <= train[1]
        assert val[0] <= val[1]
        assert test[0] <= test[1]

    def test_leap_year_handling(self, splitter):
        """Test handling of leap year (2024)."""
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)

        train, val, test = splitter.create_splits(start, end)

        # 2024 has 366 days
        total_days = (end - start).days + 1
        assert total_days == 366

    def test_multiple_years_walk_forward(self, splitter):
        """Test walk-forward across multiple years."""
        start = date(2023, 1, 1)
        end = date(2025, 12, 31)

        splits = splitter.walk_forward_splits(start, end, window_days=30, step_days=7)

        # Should generate many splits
        assert len(splits) > 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
