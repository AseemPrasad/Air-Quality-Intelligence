"""
Location-level aggregation from multi-station air quality data.

Aggregates measurements from multiple monitoring stations into
location-level statistics, including median, mean, percentiles,
coverage, and quality tracking.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import math
import statistics


class LocationAggregator:
    """Aggregate station-level observations into location-level statistics."""

    def __init__(
        self,
        storage_root: str = "data/raw",
        measurement_interval_minutes: int = 60,
    ):
        if measurement_interval_minutes <= 0:
            raise ValueError("measurement_interval_minutes must be positive")

        self.storage_root = Path(storage_root)
        self.measurement_interval_minutes = measurement_interval_minutes

    # ---------------------------------------------------------
    # Station discovery
    # ---------------------------------------------------------

    def _get_location_stations(self, location_id: str) -> List[str]:
        """
        Return station IDs associated with a location.

        Expected directory structure:

        data/raw/
            kolkata/
                station_1/
                station_2/
                station_3/
        """
        location_path = self.storage_root / location_id

        if not location_path.exists() or not location_path.is_dir():
            return []

        return sorted(
            path.name
            for path in location_path.iterdir()
            if path.is_dir()
        )

    # ---------------------------------------------------------
    # Station data loading
    # ---------------------------------------------------------

    def _get_station_hourly_values(
        self,
        station_id: str,
        location_id: str = "",
        pollutant: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        time_window_hours: int = 24,
        **kwargs,
    ) -> Tuple[List[float], Dict[str, int]]:
        """
        Retrieve station observations.

        This method is intended to be overridden or connected to
        your existing data loader.

        Returns:
            Tuple containing:
                - list of valid numerical observations
                - quality counts (valid, suspicious)
        """
        return [], {"valid": 0, "suspicious": 0}

    # ---------------------------------------------------------
    # Expected observations
    # ---------------------------------------------------------

    def _calculate_expected_observations(
        self,
        station_count: int,
        time_window_hours: float,
    ) -> int:
        """Calculate the expected number of measurements."""

        observations_per_hour = (
            60 / self.measurement_interval_minutes
        )

        expected = (
            observations_per_hour
            * station_count
            * time_window_hours
        )

        return int(round(expected))

    # ---------------------------------------------------------
    # Percentile calculation
    # ---------------------------------------------------------

    @staticmethod
    def _percentile(
        values: List[float],
        percentile: float,
    ) -> Optional[float]:
        """
        Calculate percentile using linear interpolation.

        percentile must be between 0 and 1.
        """

        if not values:
            return None

        if not 0 <= percentile <= 1:
            raise ValueError("percentile must be between 0 and 1")

        sorted_values = sorted(values)

        if len(sorted_values) == 1:
            return float(sorted_values[0])

        position = percentile * (len(sorted_values) - 1)

        lower_index = math.floor(position)
        upper_index = math.ceil(position)

        if lower_index == upper_index:
            return float(sorted_values[lower_index])

        lower_value = sorted_values[lower_index]
        upper_value = sorted_values[upper_index]

        weight = position - lower_index

        return float(
            lower_value + weight * (upper_value - lower_value)
        )

    # ---------------------------------------------------------
    # Main aggregation
    # ---------------------------------------------------------

    def aggregate_stations_to_location(
        self,
        location_id: str,
        pollutant: str,
        time_window_hours: int,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate measurements from all stations at a location.
        """

        if time_window_hours <= 0:
            raise ValueError("time_window_hours must be positive")

        if end_time is None:
            end_time = datetime.now(timezone.utc)

        # Ensure datetime is timezone-aware.
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        start_time = end_time - timedelta(hours=time_window_hours)

        stations = self._get_location_stations(location_id)

        station_count = len(stations)

        all_values: List[float] = []

        active_stations = 0

        valid_stations = 0
        suspicious_stations = 0

        # -----------------------------------------------------
        # Collect observations from every station
        # -----------------------------------------------------

        for station_id in stations:

            values, quality = self._get_station_hourly_values(
                station_id=station_id,
                location_id=location_id,
                pollutant=pollutant,
                start_time=start_time,
                end_time=end_time,
                time_window_hours=time_window_hours,
            )

            if values is None:
                values = []

            if quality is None:
                quality = {}

            # Remove null, NaN and non-numeric values.
            cleaned_values = []

            for value in values:
                if value is None:
                    continue

                try:
                    numeric_value = float(value)

                    if math.isfinite(numeric_value):
                        cleaned_values.append(numeric_value)

                except (TypeError, ValueError):
                    continue

            if cleaned_values:
                active_stations += 1
                all_values.extend(cleaned_values)

            valid_stations += int(
                quality.get("valid", 0)
            )

            suspicious_stations += int(
                quality.get("suspicious", 0)
            )

        # -----------------------------------------------------
        # Calculate statistics
        # -----------------------------------------------------

        observation_count = len(all_values)

        if observation_count > 0:

            median_value = float(statistics.median(all_values))

            mean_value = float(statistics.mean(all_values))

            p25 = self._percentile(all_values, 0.25)

            p75 = self._percentile(all_values, 0.75)

            max_value = float(max(all_values))

            min_value = float(min(all_values))

        else:

            median_value = None
            mean_value = None
            p25 = None
            p75 = None
            max_value = None
            min_value = None

        # -----------------------------------------------------
        # Coverage calculation
        # -----------------------------------------------------

        expected_observations = (
            self._calculate_expected_observations(
                station_count=station_count,
                time_window_hours=time_window_hours,
            )
        )

        if expected_observations > 0:

            coverage_pct = (
                observation_count / expected_observations
            ) * 100

            # Coverage cannot exceed 100%.
            coverage_pct = min(coverage_pct, 100.0)

        else:
            coverage_pct = 0.0

        # -----------------------------------------------------
        # Output
        # -----------------------------------------------------

        return {
            "location_id": location_id,
            "pollutant": pollutant,

            "hour_start": start_time,

            "station_count": station_count,
            "active_stations": active_stations,

            "median_value": median_value,
            "mean_value": mean_value,

            "p25": p25,
            "p75": p75,

            "max_value": max_value,
            "min_value": min_value,

            "valid_stations": valid_stations,
            "suspicious_stations": suspicious_stations,

            "coverage_pct": round(coverage_pct, 2),

            "observation_count": observation_count,

            "aggregated_at": datetime.now(timezone.utc),
        }

    # ---------------------------------------------------------
    # Batch aggregation
    # ---------------------------------------------------------

    def aggregate_batch(
        self,
        location_id: str,
        pollutants: List[str],
        time_window_hours: int,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Aggregate multiple pollutants for a single location.

        Pollutant order is preserved.
        """

        results = []

        for pollutant in pollutants:

            result = self.aggregate_stations_to_location(
                location_id=location_id,
                pollutant=pollutant,
                time_window_hours=time_window_hours,
                end_time=end_time,
            )

            results.append(result)

        return results
