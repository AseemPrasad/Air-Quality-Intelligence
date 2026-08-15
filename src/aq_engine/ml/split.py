"""Time-series split logic for ML model evaluation and training.

Implements chronological splits (no random shuffling) and walk-forward validation
to prevent data leakage and simulate production retraining scenarios.
"""

import logging
from datetime import datetime, timedelta, date
from typing import Tuple, List, Union

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class TimeSeriesSplitter:
    """Splits time-series data chronologically for ML model evaluation.

    Ensures strict temporal order: train < val < test.
    No random shuffling; all observations used in order.

    Example:
        >>> splitter = TimeSeriesSplitter()
        >>> train, val, test = splitter.create_splits(
        ...     start_date=date(2023, 1, 1),
        ...     end_date=date(2025, 12, 31),
        ...     train_pct=0.7,
        ...     val_pct=0.15
        ... )
        >>> print(f"Train: {train[0]} to {train[1]}")
        >>> print(f"Val: {val[0]} to {val[1]}")
        >>> print(f"Test: {test[0]} to {test[1]}")
    """

    def __init__(self):
        """Initialize time-series splitter."""
        pass

    def create_splits(
        self,
        start_date: Union[date, datetime],
        end_date: Union[date, datetime],
        train_pct: float = 0.7,
        val_pct: float = 0.15,
    ) -> Tuple[
        Tuple[Union[date, datetime], Union[date, datetime]],
        Tuple[Union[date, datetime], Union[date, datetime]],
        Tuple[Union[date, datetime], Union[date, datetime]],
    ]:
        """Create chronological train/val/test splits.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            train_pct: Fraction for training (default 0.70)
            val_pct: Fraction for validation (default 0.15)
            (test_pct = 1.0 - train_pct - val_pct)

        Returns:
            Tuple of ((train_start, train_end), (val_start, val_end), (test_start, test_end))

        Raises:
            ValueError: If percentages invalid or date range invalid
        """
        # Normalize dates to date objects for consistent handling
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()

        # Validate inputs
        if train_pct <= 0 or train_pct >= 1:
            raise ValueError(f"train_pct must be in (0, 1), got {train_pct}")
        if val_pct <= 0 or val_pct >= 1:
            raise ValueError(f"val_pct must be in (0, 1), got {val_pct}")
        if train_pct + val_pct >= 1:
            raise ValueError(
                f"train_pct + val_pct must be < 1, got {train_pct + val_pct}"
            )
        if start_date >= end_date:
            raise ValueError(f"start_date must be before end_date")

        # Calculate total days (inclusive)
        total_days = (end_date - start_date).days + 1

        # Calculate split sizes
        train_days = int(total_days * train_pct)
        val_days = int(total_days * val_pct)
        test_days = total_days - train_days - val_days

        # Ensure at least 1 day for each split
        if train_days < 1 or val_days < 1 or test_days < 1:
            raise ValueError(
                f"Date range too small for splits: "
                f"total_days={total_days}, train={train_days}, val={val_days}, test={test_days}"
            )

        # Calculate split boundaries
        train_start = start_date
        train_end = train_start + timedelta(days=train_days - 1)  # -1 for inclusive

        val_start = train_end + timedelta(days=1)
        val_end = val_start + timedelta(days=val_days - 1)

        test_start = val_end + timedelta(days=1)
        test_end = end_date

        logger.info(
            f"Created time-series splits: "
            f"train={train_start}→{train_end} ({train_days}d), "
            f"val={val_start}→{val_end} ({val_days}d), "
            f"test={test_start}→{test_end} ({test_days}d)"
        )

        return (train_start, train_end), (val_start, val_end), (test_start, test_end)

    def walk_forward_splits(
        self,
        start_date: Union[date, datetime],
        end_date: Union[date, datetime],
        window_days: int = 30,
        step_days: int = 7,
    ) -> List[Tuple[Tuple[Union[date, datetime], Union[date, datetime]],
                    Tuple[Union[date, datetime], Union[date, datetime]]]]:
        """Generate walk-forward validation splits.

        Simulates production retraining with expanding training window:
        - Window 1: train on [start, start+window_days], test on [start+window_days+1, start+window_days+step_days]
        - Window 2: train on [start, start+window_days+step_days], test on [start+window_days+step_days+1, start+window_days+2*step_days]
        - ... continue until end_date

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            window_days: Initial training window size in days (default 30)
            step_days: Test set size and window expansion in days (default 7)

        Returns:
            List of ((train_start, train_end), (test_start, test_end)) tuples

        Raises:
            ValueError: If parameters invalid or date range too small
        """
        # Normalize dates
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()

        # Validate inputs
        if window_days <= 0:
            raise ValueError(f"window_days must be > 0, got {window_days}")
        if step_days <= 0:
            raise ValueError(f"step_days must be > 0, got {step_days}")
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")

        total_days = (end_date - start_date).days + 1
        if total_days < window_days + step_days:
            raise ValueError(
                f"Date range too small for walk-forward: "
                f"need at least {window_days + step_days} days, got {total_days}"
            )

        splits = []

        # Initialize training window
        train_start = start_date
        train_end = start_date + timedelta(days=window_days - 1)

        # Generate splits
        while True:
            test_start = train_end + timedelta(days=1)
            test_end = min(
                test_start + timedelta(days=step_days - 1), end_date
            )

            # Stop if test window is beyond end_date
            if test_start > end_date:
                break

            splits.append(((train_start, train_end), (test_start, test_end)))

            # Expand training window for next iteration
            train_end = test_end

            # Stop if we've reached end_date
            if test_end >= end_date:
                break

        logger.info(
            f"Generated {len(splits)} walk-forward splits: "
            f"window={window_days}d, step={step_days}d, "
            f"period={start_date}→{end_date}"
        )

        return splits

    @staticmethod
    def get_date_range_days(
        start_date: Union[date, datetime],
        end_date: Union[date, datetime],
    ) -> int:
        """Get number of days in a date range (inclusive).

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            Number of days (inclusive)
        """
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()

        return (end_date - start_date).days + 1

    @staticmethod
    def split_contains_date(
        split_start: Union[date, datetime],
        split_end: Union[date, datetime],
        target_date: Union[date, datetime],
    ) -> bool:
        """Check if a date is within a split range.

        Args:
            split_start: Start of split (inclusive)
            split_end: End of split (inclusive)
            target_date: Date to check

        Returns:
            True if target_date in [split_start, split_end]
        """
        if isinstance(split_start, datetime):
            split_start = split_start.date()
        if isinstance(split_end, datetime):
            split_end = split_end.date()
        if isinstance(target_date, datetime):
            target_date = target_date.date()

        return split_start <= target_date <= split_end
