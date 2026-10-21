"""Sensor drift detection using local trends and neighbor baselines."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Iterable, List

# Records without a usable timestamp sort first. This has to be timezone-aware:
# observed_at is UTC-aware everywhere else in the pipeline, and a naive
# datetime.min cannot be compared against it.
_EARLIEST = datetime.min.replace(tzinfo=UTC)


def _observed_at_key(record: dict[str, Any]) -> datetime:
    """Sort key for a record's observed_at (datetime, ISO string or missing)."""
    value = record.get("observed_at")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return _EARLIEST
    if not isinstance(value, datetime):
        return _EARLIEST
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SensorDriftValidator:
    """Detect sustained drift in a station series relative to neighboring stations.

    The validator fits a simple linear slope over an extended window (7-14 days)
    and compares the trend against spatial neighbors. A sensor is marked as
    drifted when its slope deviates significantly from its neighbors and the
    trend persists beyond the minimum number of observations.
    """

    def __init__(
        self,
        min_points: int = 48,
        slope_threshold: float = 0.05,
        neighbor_deviation: float = 0.2,
        window_hours: int = 168,
    ):
        self.min_points = min_points
        self.slope_threshold = slope_threshold
        self.neighbor_deviation = neighbor_deviation
        self.window_hours = window_hours

    @staticmethod
    def _linear_slope(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        x_values = list(range(len(values)))
        mean_x = sum(x_values) / len(x_values)
        mean_y = sum(values) / len(values)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, values))
        denominator = sum((x - mean_x) ** 2 for x in x_values)
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def _numeric_values(window: list[dict[str, Any]]) -> list[float]:
        """Finite numeric values from a window, skipping anything unusable."""
        values = []
        for record in window:
            value = record.get("value")
            if value is None or isinstance(value, bool):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not isfinite(numeric):
                continue
            values.append(numeric)
        return values

    def flag_records(self, records: Iterable[dict[str, Any]]) -> List[dict[str, Any]]:
        """Return records flagged as DRIFT_DETECTED."""
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            station_id = str(record.get("station_id", ""))
            pollutant = str(record.get("pollutant", "")).lower()
            if not station_id or not pollutant:
                continue
            grouped[(station_id, pollutant)].append(record)

        flagged: List[dict[str, Any]] = []
        station_to_pollutant: dict[str, list[str]] = defaultdict(list)
        for (station_id, pollutant), series in grouped.items():
            station_to_pollutant[station_id].append(pollutant)

        for (station_id, pollutant), series in grouped.items():
            series.sort(key=_observed_at_key)

            if len(series) < self.min_points:
                continue

            window = series[-self.min_points :]
            values = self._numeric_values(window)

            if len(values) < self.min_points:
                continue

            slope = self._linear_slope(values)
            if abs(slope) < self.slope_threshold:
                continue

            # Compare station trend to nearby stations for same pollutant.
            neighbors = []
            for (other_station, other_pollutant), other_series in grouped.items():
                if other_station == station_id or other_pollutant != pollutant:
                    continue
                other_series_sorted = sorted(other_series, key=_observed_at_key)
                if len(other_series_sorted) < self.min_points:
                    continue
                other_window = other_series_sorted[-self.min_points :]
                # Same filtering as the station's own window: a single NaN here
                # would turn the neighbour slope, and the average, into NaN and
                # silently stop drift from ever being flagged.
                other_values = self._numeric_values(other_window)
                if len(other_values) >= self.min_points:
                    neighbors.append(self._linear_slope(other_values))

            if not neighbors:
                continue

            average_neighbor_slope = sum(neighbors) / len(neighbors)
            if abs(slope - average_neighbor_slope) >= self.neighbor_deviation:
                for record in window:
                    record["quality_flag"] = "DRIFT_DETECTED"
                    record["quality_reason"] = (
                        f"Sensor drift detected for {pollutant}: slope={slope:.4f}, "
                        f"neighbor_mean_slope={average_neighbor_slope:.4f}"
                    )
                    flagged.append(record)

        return flagged
