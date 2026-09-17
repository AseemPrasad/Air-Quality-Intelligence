"""Flatline detection for frozen sensors."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, List


class FlatlineValidator:
    """Flag records from sensors that remain constant across a sustained window.

    A sensor is considered flatlined when the rolling variance for a given
    station_id/pollutant is zero across at least ``min_hours`` consecutive
    observations. This catches hardware that continues reporting a fixed value
    while staying within normal operating ranges.
    """

    def __init__(self, min_hours: int = 6):
        self.min_hours = min_hours

    def flag_records(self, records: Iterable[dict[str, Any]]) -> List[dict[str, Any]]:
        """Return records flagged as STUCK_SENSOR.

        The method evaluates each station/pollutant series in timestamp order and
        marks the final record in a constant run as suspicious when the run length
        reaches the configured threshold.
        """
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            station_id = str(record.get("station_id", ""))
            pollutant = str(record.get("pollutant", "")).lower()
            if not station_id or not pollutant:
                continue
            grouped[(station_id, pollutant)].append(record)

        flagged: List[dict[str, Any]] = []
        for series in grouped.values():
            series.sort(key=lambda r: r.get("observed_at") or datetime.min)
            run: list[dict[str, Any]] = []
            last_value: float | None = None
            for record in series:
                value = record.get("value")
                if value is None or not isinstance(value, (int, float)):
                    run = []
                    last_value = None
                    continue

                if last_value is None or value == last_value:
                    run.append(record)
                else:
                    run = [record]
                last_value = value

                if len(run) >= self.min_hours:
                    for candidate in run[-self.min_hours :]:
                        candidate["quality_flag"] = "STUCK_SENSOR"
                        candidate["quality_reason"] = (
                            f"Flatline detected: constant {candidate.get('pollutant')} "
                            f"value for {len(run)} consecutive hours"
                        )
                        flagged.append(candidate)

        return flagged
