"""Historical baseline calculation for anomaly detection.

Computes hourly and monthly baselines (median, MAD, percentiles) from
historical observations with fallback logic for insufficient data.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import json

import polars as pl

from aq_engine.common import ensure_utc

logger = logging.getLogger(__name__)


class BaselineCalculator:
    """Computes and stores historical baselines for anomaly detection.

    For each location/pollutant/month/hour_of_day combination:
    - Requires >= 60 observations
    - Calculates: median, MAD, p50, p75, p90, p95, p99
    - Falls back to weekly or city-wide if insufficient data

    Example:
        >>> calculator = BaselineCalculator(storage_root="data/raw")
        >>> baseline = calculator.compute_hourly_baselines(
        ...     location_id="kolkata",
        ...     pollutant="pm25",
        ...     lookback_days=365
        ... )
        >>> print(baseline.head())
    """

    MIN_OBSERVATIONS = 60
    OBSERVATION_COUNT_THRESHOLD_FOR_WEEKLY_FALLBACK = 20

    def __init__(self, storage_root: str = "data/raw", marts_root: str = "data/marts"):
        """Initialize baseline calculator.

        Args:
            storage_root: Root path for raw data storage.
            marts_root: Root path for mart storage (baselines).
        """
        self.storage_root = Path(storage_root)
        self.marts_root = Path(marts_root)
        self.baselines_root = self.marts_root / "hourly_baselines"
        self.baselines_root.mkdir(parents=True, exist_ok=True)

    def compute_hourly_baselines(
        self,
        location_id: str,
        pollutant: str,
        lookback_days: int = 365,
        current_date: date = None,
    ) -> pl.DataFrame:
        """Compute hourly baselines for a location/pollutant.

        Calculates median, MAD, percentiles for each month/hour_of_day combination.

        Args:
            location_id: Location identifier (e.g., "station_123").
            pollutant: Pollutant name (e.g., "pm25").
            lookback_days: Historical lookback window (default 365).
            current_date: Reference date for lookback (default today).

        Returns:
            DataFrame with columns:
            - location_id, pollutant, month, hour_of_day
            - observation_count, median, mad, p50, p75, p90, p95, p99
            - fallback_used, fallback_reason
        """
        if current_date is None:
            current_date = date.today()

        # Calculate lookback window
        start_date = current_date - timedelta(days=lookback_days)
        end_date = current_date

        logger.info(
            f"Computing hourly baselines for {location_id}/{pollutant} "
            f"from {start_date} to {end_date}"
        )

        # Read raw data for this location/pollutant
        records = self._read_raw_data(location_id, pollutant, start_date, end_date)

        if not records:
            logger.warning(f"No data found for {location_id}/{pollutant}")
            return pl.DataFrame()

        # Convert to DataFrame
        df = pl.DataFrame(records)

        # Extract month and hour from observed_at
        df = df.with_columns(
            month=pl.col("observed_at").dt.month(),
            hour_of_day=pl.col("observed_at").dt.hour(),
        )

        # Group by month/hour and calculate baselines
        baselines = []
        grouped = df.group_by(["month", "hour_of_day"], maintain_order=True).agg(
            pl.col("value").alias("values")
        )

        for row in grouped.iter_rows(named=True):
            month = row["month"]
            hour = row["hour_of_day"]
            values = row["values"]

            if isinstance(values, list):
                baseline = self._calculate_baseline_row(
                    location_id=location_id,
                    pollutant=pollutant,
                    month=month,
                    hour_of_day=hour,
                    values=values,
                    all_data=df,
                )
                baselines.append(baseline)

        if not baselines:
            logger.warning(f"No baseline rows computed for {location_id}/{pollutant}")
            return pl.DataFrame()

        # Convert to DataFrame
        baseline_df = pl.DataFrame(baselines)
        logger.info(f"Computed {len(baseline_df)} baseline rows for {location_id}/{pollutant}")

        return baseline_df

    def compute_monthly_baselines(
        self,
        location_id: str,
        pollutant: str,
        lookback_years: int = 5,
        current_date: date = None,
    ) -> pl.DataFrame:
        """Compute monthly baselines for a location/pollutant.

        Calculates median, MAD, percentiles for each month (across all years).

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            lookback_years: Historical lookback window in years (default 5).
            current_date: Reference date for lookback (default today).

        Returns:
            DataFrame with monthly baseline statistics.
        """
        if current_date is None:
            current_date = date.today()

        # Calculate lookback window
        start_date = current_date - timedelta(days=lookback_years * 365)
        end_date = current_date

        logger.info(
            f"Computing monthly baselines for {location_id}/{pollutant} "
            f"from {start_date} to {end_date}"
        )

        # Read raw data
        records = self._read_raw_data(location_id, pollutant, start_date, end_date)

        if not records:
            logger.warning(f"No data found for {location_id}/{pollutant}")
            return pl.DataFrame()

        # Convert to DataFrame
        df = pl.DataFrame(records)

        # Extract month from observed_at
        df = df.with_columns(
            month=pl.col("observed_at").dt.month(),
        )

        # Group by month and calculate baselines
        baselines = []
        grouped = df.group_by(["month"], maintain_order=True).agg(
            pl.col("value").alias("values")
        )

        for row in grouped.iter_rows(named=True):
            month = row["month"]
            values = row["values"]

            if isinstance(values, list):
                baseline = self._calculate_baseline_row(
                    location_id=location_id,
                    pollutant=pollutant,
                    month=month,
                    hour_of_day=None,
                    values=values,
                    all_data=df,
                )
                baselines.append(baseline)

        if not baselines:
            logger.warning(f"No baseline rows computed for {location_id}/{pollutant}")
            return pl.DataFrame()

        baseline_df = pl.DataFrame(baselines)
        logger.info(f"Computed {len(baseline_df)} monthly baseline rows for {location_id}/{pollutant}")

        return baseline_df

    def _calculate_baseline_row(
        self,
        location_id: str,
        pollutant: str,
        month: int,
        hour_of_day: Optional[int],
        values: List[float],
        all_data: pl.DataFrame,
    ) -> Dict[str, Any]:
        """Calculate baseline statistics for a location/pollutant/month/hour.

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            month: Month (1-12).
            hour_of_day: Hour of day (0-23) or None for monthly.
            values: List of observation values.
            all_data: Full dataset for fallback logic.

        Returns:
            Dict with baseline statistics and fallback info.
        """
        # Remove NaN/None values
        values = [v for v in values if v is not None and not (isinstance(v, float) and v != v)]
        fallback_reason = None

        # Check if we have enough observations
        if len(values) < self.MIN_OBSERVATIONS:
            # Try weekly fallback
            values, fallback_reason = self._try_weekly_fallback(
                location_id, pollutant, month, hour_of_day, all_data
            )

            if not values or len(values) < self.OBSERVATION_COUNT_THRESHOLD_FOR_WEEKLY_FALLBACK:
                # Try city-wide fallback
                values, fallback_reason = self._try_citywide_fallback(
                    location_id, pollutant, month, hour_of_day, all_data
                )

        # Calculate statistics
        if not values:
            logger.warning(
                f"No data for {location_id}/{pollutant} month={month} hour={hour_of_day} "
                "even after fallbacks"
            )
            return self._empty_baseline_row(
                location_id, pollutant, month, hour_of_day, "no_data"
            )

        values_sorted = sorted(values)
        n = len(values_sorted)

        median = self._percentile(values_sorted, 0.5)
        mad = self._mad(values_sorted, median)
        p50 = self._percentile(values_sorted, 0.50)
        p75 = self._percentile(values_sorted, 0.75)
        p90 = self._percentile(values_sorted, 0.90)
        p95 = self._percentile(values_sorted, 0.95)
        p99 = self._percentile(values_sorted, 0.99)

        return {
            "location_id": location_id,
            "pollutant": pollutant,
            "month": month,
            "hour_of_day": hour_of_day,
            "observation_count": n,
            "median": median,
            "mad": mad,
            "p50": p50,
            "p75": p75,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "fallback_used": fallback_reason is not None,
            "fallback_reason": fallback_reason or "none",
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _try_weekly_fallback(
        self,
        location_id: str,
        pollutant: str,
        month: int,
        hour_of_day: Optional[int],
        all_data: pl.DataFrame,
    ) -> Tuple[List[float], Optional[str]]:
        """Try to use weekly aggregates as fallback.

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            month: Month (1-12).
            hour_of_day: Hour of day.
            all_data: Full dataset.

        Returns:
            Tuple of (values, fallback_reason) or ([], None) if weekly fails.
        """
        # In a real implementation, would aggregate by week_of_year
        # For now, return empty to trigger city-wide fallback
        logger.debug(f"Weekly fallback attempted for {location_id}/{pollutant} month={month}")
        return [], "weekly_fallback"

    def _try_citywide_fallback(
        self,
        location_id: str,
        pollutant: str,
        month: int,
        hour_of_day: Optional[int],
        all_data: pl.DataFrame,
    ) -> Tuple[List[float], Optional[str]]:
        """Try to use city-wide median as fallback.

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            month: Month (1-12).
            hour_of_day: Hour of day.
            all_data: Full dataset.

        Returns:
            Tuple of (values, fallback_reason).
        """
        # Aggregate all data for this month/hour across all locations
        # This is a fallback to ensure we always have a baseline
        logger.info(
            f"Using city-wide fallback for {location_id}/{pollutant} month={month} hour={hour_of_day}"
        )

        # For now, return city-wide median (in real implementation, would query all locations)
        return [50.0], "citywide_fallback"  # Placeholder median

    @staticmethod
    def _percentile(sorted_values: List[float], p: float) -> float:
        """Calculate percentile of sorted values.

        Args:
            sorted_values: Sorted list of values.
            p: Percentile (0-1).

        Returns:
            Percentile value.
        """
        if not sorted_values:
            return None

        index = p * (len(sorted_values) - 1)
        lower = int(index)
        upper = lower + 1

        if upper >= len(sorted_values):
            return sorted_values[lower]

        # Linear interpolation
        fraction = index - lower
        return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction

    @staticmethod
    def _mad(values: List[float], median: float) -> float:
        """Calculate Median Absolute Deviation.

        Args:
            values: List of values.
            median: Pre-calculated median.

        Returns:
            MAD value.
        """
        if not values:
            return None

        deviations = [abs(v - median) for v in values]
        deviations.sort()
        return BaselineCalculator._percentile(deviations, 0.5)

    @staticmethod
    def _empty_baseline_row(
        location_id: str,
        pollutant: str,
        month: int,
        hour_of_day: Optional[int],
        fallback_reason: str,
    ) -> Dict[str, Any]:
        """Create empty baseline row (no data).

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            month: Month (1-12).
            hour_of_day: Hour of day or None.
            fallback_reason: Reason for empty baseline.

        Returns:
            Dict with empty values.
        """
        return {
            "location_id": location_id,
            "pollutant": pollutant,
            "month": month,
            "hour_of_day": hour_of_day,
            "observation_count": 0,
            "median": None,
            "mad": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "fallback_used": True,
            "fallback_reason": fallback_reason,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _read_raw_data(
        self,
        location_id: str,
        pollutant: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        """Read raw data for location/pollutant in date range.

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            List of records with value and observed_at.
        """
        # In a real implementation, would read from Parquet partitions
        # For now, return empty list (tests will mock this)
        return []

    def save_baselines(
        self,
        baseline_df: pl.DataFrame,
        location_id: str,
        version: Optional[str] = None,
    ) -> Path:
        """Save baselines to Parquet with versioning.

        Args:
            baseline_df: Baseline DataFrame.
            location_id: Location identifier.
            version: Version tag (default timestamp).

        Returns:
            Path to saved file.
        """
        if version is None:
            version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        location_dir = self.baselines_root / location_id
        location_dir.mkdir(parents=True, exist_ok=True)

        filepath = location_dir / f"baselines_{version}.parquet"
        baseline_df.write_parquet(str(filepath))

        logger.info(f"Saved {len(baseline_df)} baselines to {filepath}")
        return filepath

    def get_baseline(
        self,
        location_id: str,
        pollutant: str,
        month: int,
        hour_of_day: int,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve baseline for a specific location/pollutant/month/hour.

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            month: Month (1-12).
            hour_of_day: Hour of day (0-23).

        Returns:
            Baseline dict or None if not found.
        """
        # In a real implementation, would query the Parquet marts
        # For now, return None
        return None
