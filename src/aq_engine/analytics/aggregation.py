"""Location-level aggregation from multi-station measurements.

Rolls up hourly means from multiple stations to single location-level estimates
using median (robust) and additional percentiles for operational dashboards.
"""

import logging
from datetime import datetime, timedelta, timezone, date
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

import polars as pl

from aq_engine.common import ensure_utc, round_to_hour

logger = logging.getLogger(__name__)


class LocationAggregator:
    """Aggregates multi-station measurements to location level.

    For operational dashboards, prefers median over mean for robustness.
    Includes coverage metrics and data quality counts.

    Example:
        >>> aggregator = LocationAggregator(
        ...     storage_root="data/raw",
        ...     measurement_interval_minutes=60
        ... )
        >>> agg = aggregator.aggregate_stations_to_location(
        ...     location_id="kolkata",
        ...     pollutant="pm25",
        ...     time_window_hours=24
        ... )
        >>> print(agg["median_value"], agg["coverage_pct"])
    """

    def __init__(
        self,
        storage_root: str = "data/raw",
        measurement_interval_minutes: int = 60,
    ):
        """Initialize location aggregator.

        Args:
            storage_root: Root path for raw data storage.
            measurement_interval_minutes: Expected measurement interval (default 60 min).
        """
        self.storage_root = storage_root
        self.measurement_interval_minutes = measurement_interval_minutes

    def aggregate_stations_to_location(
        self,
        location_id: str,
        pollutant: str,
        time_window_hours: int = 24,
        end_time: datetime = None,
    ) -> Dict[str, Any]:
        """Aggregate hourly measurements from stations to location level.

        Args:
            location_id: Location identifier (e.g., "kolkata").
            pollutant: Pollutant name (e.g., "pm25").
            time_window_hours: Time window for aggregation (default 24 hours).
            end_time: End time for aggregation (default now).

        Returns:
            Dict with:
            - location_id, pollutant, hour_start (window start time)
            - station_count, median_value, mean_value, p25, p75, max_value
            - valid_stations, suspicious_stations
            - coverage_pct (percent of expected observations received)
            - aggregated_at (timestamp)

        Example:
            >>> result = aggregator.aggregate_stations_to_location(
            ...     location_id="kolkata",
            ...     pollutant="pm25",
            ...     time_window_hours=24
            ... )
            >>> print(f"Location median: {result['median_value']}")
            >>> print(f"Coverage: {result['coverage_pct']}%")
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        else:
            end_time = ensure_utc(end_time)

        start_time = end_time - timedelta(hours=time_window_hours)
        hour_start = round_to_hour(start_time)

        logger.info(
            f"Aggregating {location_id}/{pollutant} "
            f"from {start_time} to {end_time}"
        )

        # Get all stations for this location
        stations = self._get_location_stations(location_id)
        if not stations:
            logger.warning(f"No stations found for location {location_id}")
            return self._empty_aggregation(location_id, pollutant, hour_start)

        # Fetch hourly data for each station
        station_values = {}
        valid_station_count = 0
        suspicious_station_count = 0

        for station_id in stations:
            values, quality_counts = self._get_station_hourly_values(
                station_id=station_id,
                pollutant=pollutant,
                start_time=start_time,
                end_time=end_time,
            )

            if values:
                station_values[station_id] = values
                valid_station_count += quality_counts.get("valid", 0)
                suspicious_station_count += quality_counts.get("suspicious", 0)

        if not station_values:
            logger.warning(
                f"No data found for any station in {location_id}/{pollutant}"
            )
            return self._empty_aggregation(
                location_id, pollutant, hour_start, station_count=len(stations)
            )

        # Calculate location-level statistics
        all_values = []
        for values in station_values.values():
            all_values.extend(values)

        # Calculate statistics
        all_values_sorted = sorted([v for v in all_values if v is not None])

        if not all_values_sorted:
            logger.warning(
                f"No valid values for {location_id}/{pollutant} in time window"
            )
            return self._empty_aggregation(
                location_id, pollutant, hour_start, station_count=len(stations)
            )

        median_value = self._percentile(all_values_sorted, 0.5)
        mean_value = sum(all_values_sorted) / len(all_values_sorted) if all_values_sorted else None
        p25 = self._percentile(all_values_sorted, 0.25)
        p75 = self._percentile(all_values_sorted, 0.75)
        max_value = max(all_values_sorted)

        # Calculate coverage
        active_stations = len(station_values)
        expected_obs = self._calculate_expected_observations(
            active_stations, time_window_hours
        )
        actual_obs = valid_station_count + suspicious_station_count
        coverage_pct = (actual_obs / expected_obs * 100) if expected_obs > 0 else 0.0

        result = {
            "location_id": location_id,
            "pollutant": pollutant,
            "hour_start": hour_start.isoformat(),
            "time_window_hours": time_window_hours,
            "station_count": len(stations),
            "active_stations": active_stations,
            "median_value": median_value,
            "mean_value": mean_value,
            "p25": p25,
            "p75": p75,
            "max_value": max_value,
            "min_value": min(all_values_sorted),
            "valid_stations": valid_station_count,
            "suspicious_stations": suspicious_station_count,
            "coverage_pct": coverage_pct,
            "observation_count": len(all_values_sorted),
            "expected_observation_count": expected_obs,
            "aggregated_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"Aggregated {location_id}/{pollutant}: "
            f"{active_stations} stations, median={median_value:.1f}, "
            f"coverage={coverage_pct:.1f}%"
        )

        return result

    def aggregate_batch(
        self,
        location_id: str,
        pollutants: List[str],
        time_window_hours: int = 24,
        end_time: datetime = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate multiple pollutants for a location.

        Args:
            location_id: Location identifier.
            pollutants: List of pollutant names.
            time_window_hours: Time window for aggregation.
            end_time: End time for aggregation.

        Returns:
            List of aggregation dicts, one per pollutant.
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

    def _get_location_stations(self, location_id: str) -> List[str]:
        """Get list of active stations for a location.

        Args:
            location_id: Location identifier.

        Returns:
            List of station IDs.
        """
        # In real implementation, would query location-to-station mapping from database
        # For now, return empty (tests will mock this)
        logger.debug(f"Fetching stations for location {location_id}")
        return []

    def _get_station_hourly_values(
        self,
        station_id: str,
        pollutant: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Tuple[List[float], Dict[str, int]]:
        """Get hourly mean values for a station in time window.

        Args:
            station_id: Station identifier.
            pollutant: Pollutant name.
            start_time: Window start time.
            end_time: Window end time.

        Returns:
            Tuple of (values, quality_counts) where quality_counts has "valid" and "suspicious" counts.
        """
        # In real implementation, would query from Parquet raw data
        # For now, return empty (tests will mock this)
        return [], {"valid": 0, "suspicious": 0}

    def _calculate_expected_observations(
        self,
        station_count: int,
        time_window_hours: int,
    ) -> int:
        """Calculate expected observation count.

        Expected = (observations per hour per station) * station_count * hours
        = (60 / interval_minutes) * station_count * time_window_hours

        Args:
            station_count: Number of stations.
            time_window_hours: Time window in hours.

        Returns:
            Expected observation count.
        """
        obs_per_hour_per_station = 60 // self.measurement_interval_minutes
        expected = obs_per_hour_per_station * station_count * time_window_hours
        return expected

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
    def _empty_aggregation(
        location_id: str,
        pollutant: str,
        hour_start: datetime,
        station_count: int = 0,
    ) -> Dict[str, Any]:
        """Create empty aggregation result (no data).

        Args:
            location_id: Location identifier.
            pollutant: Pollutant name.
            hour_start: Window start time.
            station_count: Number of stations in location.

        Returns:
            Dict with empty/null values.
        """
        return {
            "location_id": location_id,
            "pollutant": pollutant,
            "hour_start": hour_start.isoformat(),
            "station_count": station_count,
            "active_stations": 0,
            "median_value": None,
            "mean_value": None,
            "p25": None,
            "p75": None,
            "max_value": None,
            "min_value": None,
            "valid_stations": 0,
            "suspicious_stations": 0,
            "coverage_pct": 0.0,
            "observation_count": 0,
            "expected_observation_count": 0,
            "aggregated_at": datetime.now(timezone.utc).isoformat(),
        }
