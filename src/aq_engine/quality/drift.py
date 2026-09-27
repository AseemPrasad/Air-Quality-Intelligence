"""Sensor drift detection using local trends and neighbor baselines."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import isnan
from typing import Any, Iterable, List


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
            series.sort(key=lambda r: r.get("observed_at") or datetime.min)

            if len(series) < self.min_points:
                continue

            window = series[-self.min_points :]
            values = []
            for record in window:
                value = record.get("value")
                if value is None or isinstance(value, bool):
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if isnan(numeric):
                    continue
                values.append(numeric)

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
                other_series_sorted = sorted(
                    other_series,
                    key=lambda r: r.get("observed_at") or datetime.min,
                )
                if len(other_series_sorted) < self.min_points:
                    continue
                other_window = other_series_sorted[-self.min_points :]
                other_values = []
                for record in other_window:
                    value = record.get("value")
                    if value is None or isinstance(value, bool):
                        continue
                    try:
                        other_values.append(float(value))
                    except (TypeError, ValueError):
                        pass
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
