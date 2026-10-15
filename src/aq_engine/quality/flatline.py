"""Flatline detection for frozen sensors."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, List


class FlatlineValidator:
    """Flag records from sensors that remain constant across a sustained window.

    A sensor is considered flatlined when the same value is observed across
    at least ``min_hours`` consecutive hourly observations for a given
    station_id/pollutant. This catches hardware that continues reporting
    a fixed value while staying within normal operating ranges.

    Hourly cadence is enforced using ``observed_at``. Readings that arrive
    minutes apart do not satisfy an hourly check, and a missing hour breaks
    the run, so ``min_hours`` keeps its documented meaning of hours rather
    than raw sample count.
    """

    # Gaps between consecutive rows that can still count as hourly.
    # Allows 15 minutes early / 30 minutes late for clock skew and late jobs.
    MIN_HOURLY_GAP_SECONDS = 45 * 60
    MAX_HOURLY_GAP_SECONDS = 90 * 60

    # Average gap required across the flagged window. Allows about 5 minutes
    # early per hour on average so slightly jittered hourly feeds still pass
    # while short high-frequency bursts cannot accumulate enough wall time.
    MIN_AVG_GAP_SECONDS = 55 * 60

    def __init__(self, min_hours: int = 6):
        self.min_hours = min_hours

    @staticmethod
    def _parse_observed_at(value: Any) -> datetime | None:
        """Return ``value`` as UTC datetime, or None when unusable."""
        if isinstance(value, datetime):
            try:
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                return None
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text[-1] in ("Z", "z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
            try:
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                return None
        return None

    def flag_records(self, records: Iterable[dict[str, Any]]) -> List[dict[str, Any]]:
        """Return records flagged as STUCK_SENSOR.

        The method evaluates each station/pollutant series in timestamp order
        and marks records in a constant run as suspicious once the run holds
        at least ``min_hours`` hourly observations spanning
        ``min_hours - 1`` hours of wall time. Runs break on value changes,
        non-numeric values, missing timestamps, and gaps that are clearly
        not hourly.
        """
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            station_id = str(record.get("station_id", ""))
            pollutant = str(record.get("pollutant", "")).lower()
            if not station_id or not pollutant:
                continue
            grouped[(station_id, pollutant)].append(record)

        flagged: List[dict[str, Any]] = []
        seen: set[int] = set()
        for series in grouped.values():
            series.sort(
                key=lambda r: self._parse_observed_at(r.get("observed_at"))
                or datetime.min.replace(tzinfo=timezone.utc)
            )
            run: list[dict[str, Any]] = []
            run_times: list[datetime] = []
            last_value: float | None = None
            last_ts: datetime | None = None
            for record in series:
                value = record.get("value")
                if (
                    value is None
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    run = []
                    run_times = []
                    last_value = None
                    last_ts = None
                    continue

                observed = self._parse_observed_at(record.get("observed_at"))
                if observed is None:
                    run = []
                    run_times = []
                    last_value = None
                    last_ts = None
                    continue

                if last_value is None or value != last_value:
                    run = [record]
                    run_times = [observed]
                else:
                    gap = (observed - last_ts).total_seconds() if last_ts else 0
                    if (
                        gap < self.MIN_HOURLY_GAP_SECONDS
                        or gap > self.MAX_HOURLY_GAP_SECONDS
                    ):
                        run = [record]
                        run_times = [observed]
                    else:
                        run.append(record)
                        run_times.append(observed)
                last_value = value
                last_ts = observed

                if len(run) >= self.min_hours:
                    span = (run_times[-1] - run_times[0]).total_seconds()
                    required = (self.min_hours - 1) * self.MIN_AVG_GAP_SECONDS
                    if span + 1e-6 < required:
                        continue
                    for candidate in run[-self.min_hours :]:
                        if id(candidate) in seen:
                            continue
                        seen.add(id(candidate))
                        span_hours = span / 3600
                        candidate["quality_flag"] = "STUCK_SENSOR"
                        candidate["quality_reason"] = (
                            f"Flatline detected: constant {candidate.get('pollutant')} "
                            f"value for {len(run)} consecutive hourly observations "
                            f"spanning {span_hours:.1f}h"
                        )
                        flagged.append(candidate)

        return flagged
