"""Late-arrival observation handling and recomputation marking.

Classifies observations based on age relative to current time:
- Within lookback (6h): Mark affected hourly partitions for recomputation
- Beyond lookback (>6h): Treat as historical/backfill data

Fix (Issue #15): All latency calculations now use strictly UTC-aware datetime
objects via ``ensure_utc()``.  Previously, mixing naive datetimes with
aware ones raised ``TypeError: can't compare offset-naive and offset-aware
datetimes``, and stripping timezone info via ``.replace(tzinfo=None)``
produced silent latency skew on non-UTC hosts.
"""

import logging
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Tuple, Any, Optional
from enum import Enum

from aq_engine.common import ensure_utc, round_to_hour

logger = logging.getLogger(__name__)


def is_late_arrival(record_time: datetime, max_delay_hours: int = 3) -> bool:
    """Return True if *record_time* is older than *max_delay_hours* ago.

    The comparison is always performed in UTC so that the result is the same
    regardless of the host's local timezone setting.

    If *record_time* carries no ``tzinfo`` it is assumed to represent UTC (the
    same assumption used throughout the ingestion pipeline).

    Args:
        record_time: Observation timestamp (naive or timezone-aware).
        max_delay_hours: Delay threshold in hours (default 3).

    Returns:
        True if the record is a late arrival, False otherwise.

    Raises:
        TypeError: If *record_time* is not a :class:`datetime` object.

    Example:
        >>> from datetime import datetime, timezone, timedelta
        >>> recent = datetime.now(timezone.utc) - timedelta(hours=1)
        >>> is_late_arrival(recent, max_delay_hours=3)
        False
        >>> old = datetime.now(timezone.utc) - timedelta(hours=5)
        >>> is_late_arrival(old, max_delay_hours=3)
        True
    """
    record_time_utc = ensure_utc(record_time)
    now_utc = datetime.now(timezone.utc)
    return (now_utc - record_time_utc).total_seconds() > (max_delay_hours * 3600)


def evaluate_record_delay(
    record_time: datetime,
    reference_time: Optional[datetime] = None,
) -> timedelta:
    """Return the delay between *record_time* and *reference_time*.

    Both timestamps are normalised to UTC before subtraction so that the
    calculation is correct even when the host is in a non-UTC timezone or
    when one timestamp carries explicit offset information and the other does
    not.

    Args:
        record_time: Observation timestamp (naive or timezone-aware).
        reference_time: Reference "now" for comparison.  Defaults to the
            actual current UTC time when *None* is supplied.

    Returns:
        A :class:`timedelta` representing how old the record is relative to
        *reference_time*.  Negative values indicate a future-dated record.

    Raises:
        TypeError: If either argument is not a :class:`datetime` object.

    Example:
        >>> from datetime import datetime, timezone, timedelta
        >>> ref = datetime(2026, 3, 12, 15, 0, 0, tzinfo=timezone.utc)
        >>> rec = datetime(2026, 3, 12, 12, 0, 0, tzinfo=timezone.utc)
        >>> evaluate_record_delay(rec, reference_time=ref)
        datetime.timedelta(seconds=10800)
    """
    record_time_utc = ensure_utc(record_time)
    if reference_time is None:
        ref_utc = datetime.now(timezone.utc)
    else:
        ref_utc = ensure_utc(reference_time)

    return ref_utc - record_time_utc


class LateArrivalClassification(str, Enum):
    """Classification of late-arriving observations."""

    IMMEDIATE = "IMMEDIATE"  # Within last hour
    RECENT = "RECENT"  # 1-6 hours old
    BACKFILL = "BACKFILL"  # >6 hours old


class LateLookbackProcessor:
    """Processes late-arriving observations.

    Policy:
    - Within 6 hours of current time: mark affected hourly partitions for recomputation
    - Beyond 6 hours: treat as backfill (no recomputation needed)

    Example:
        >>> processor = LateLookbackProcessor(lookback_hours=6)
        >>> records = [...]
        >>> result = processor.classify_and_mark(records)
        >>> print(f"Immediate: {result['immediate_count']}")
        >>> print(f"Recompute partitions: {result['affected_hourly_partitions']}")
    """

    def __init__(self, lookback_hours: float = 6.0):
        """Initialize late-arrival processor.

        Args:
            lookback_hours: Hours to consider as "recent" (default 6).
        """
        self.lookback_window = timedelta(hours=lookback_hours)
        self.lookback_hours = lookback_hours

    def classify_and_mark(
        self,
        records: List[dict],
        current_time: datetime = None,
    ) -> Dict[str, Any]:
        """Classify records and mark affected partitions.

        Args:
            records: List of records with observed_at timestamps.
            current_time: Current time for comparison (default now).

        Returns:
            Dict with:
            - immediate_count: Records <1 hour old
            - recent_count: Records 1-6 hours old
            - backfill_count: Records >6 hours old
            - affected_hourly_partitions: Set of (date, hour) tuples for recomputation
            - recomputation_marked: True if any partitions need recomputation
            - classification: List of (record, classification) tuples
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        else:
            current_time = ensure_utc(current_time)

        immediate = []
        recent = []
        backfill = []
        affected_partitions = set()
        classification_list = []

        for record in records:
            observed_at = record.get("observed_at")
            if not isinstance(observed_at, datetime):
                logger.warning(f"Record missing datetime observed_at: {record}")
                continue

            observed_at = ensure_utc(observed_at)
            age = current_time - observed_at

            # Classify by age
            if age <= timedelta(hours=1):
                classification = LateArrivalClassification.IMMEDIATE
                immediate.append(record)
            elif age <= self.lookback_window:
                classification = LateArrivalClassification.RECENT
                recent.append(record)
            else:
                classification = LateArrivalClassification.BACKFILL
                backfill.append(record)

            classification_list.append((record, classification))

            # Mark affected hourly partitions for records within lookback
            if age <= self.lookback_window:
                hourly_partition = self._get_hourly_partition(observed_at)
                affected_partitions.add(hourly_partition)

        # Log recomputation requirements
        if affected_partitions:
            logger.info(
                f"Late arrivals detected: {len(immediate)} immediate + {len(recent)} recent. "
                f"Marked {len(affected_partitions)} hourly partitions for recomputation"
            )

        return {
            "immediate_count": len(immediate),
            "recent_count": len(recent),
            "backfill_count": len(backfill),
            "total": len(records),
            "affected_hourly_partitions": affected_partitions,
            "recomputation_marked": len(affected_partitions) > 0,
            "classification": classification_list,
            "immediate_records": immediate,
            "recent_records": recent,
            "backfill_records": backfill,
        }

    def needs_recomputation(self, record: dict) -> bool:
        """Check if record requires hourly partition recomputation.

        Args:
            record: Record with observed_at timestamp.

        Returns:
            True if record is within lookback window.
        """
        observed_at = record.get("observed_at")
        if not isinstance(observed_at, datetime):
            return False

        observed_at = ensure_utc(observed_at)
        current_time = datetime.now(timezone.utc)
        age = current_time - observed_at

        return age <= self.lookback_window

    def get_affected_hourly_partition(self, record: dict) -> Tuple[date, int]:
        """Get hourly partition affected by a record.

        The hourly partition includes all observations in the same hour as the record.

        Args:
            record: Record with observed_at timestamp.

        Returns:
            Tuple of (date, hour) where hour is 0-23.

        Example:
            >>> record = {"observed_at": datetime(2026, 8, 15, 8, 30)}
            >>> partition = processor.get_affected_hourly_partition(record)
            >>> print(partition)  # (date(2026, 8, 15), 8)
        """
        observed_at = record.get("observed_at")
        if not isinstance(observed_at, datetime):
            return None

        return self._get_hourly_partition(observed_at)

    @staticmethod
    def _get_hourly_partition(timestamp: datetime) -> Tuple[date, int]:
        """Convert timestamp to hourly partition (date, hour).

        Example:
            >>> ts = datetime(2026, 8, 15, 8, 30, 45)
            >>> partition = LateLookbackProcessor._get_hourly_partition(ts)
            >>> print(partition)  # (date(2026, 8, 15), 8)
        """
        hourly = round_to_hour(timestamp)
        return (hourly.date(), hourly.hour)

    def get_lookback_window_range(
        self, current_time: datetime = None
    ) -> Tuple[datetime, datetime]:
        """Get start and end of lookback window.

        Args:
            current_time: Current time for reference (default now).

        Returns:
            Tuple of (window_start, window_end).
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        else:
            current_time = ensure_utc(current_time)

        window_start = current_time - self.lookback_window
        return (window_start, current_time)

    def split_records_by_lookback(
        self, records: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """Split records into lookback (needs recomputation) and backfill (no recomputation).

        Args:
            records: List of records with observed_at timestamps.

        Returns:
            Tuple of (lookback_records, backfill_records).
        """
        lookback = []
        backfill = []

        current_time = datetime.now(timezone.utc)

        for record in records:
            observed_at = record.get("observed_at")
            if not isinstance(observed_at, datetime):
                backfill.append(record)
                continue

            observed_at = ensure_utc(observed_at)
            age = current_time - observed_at

            if age <= self.lookback_window:
                lookback.append(record)
            else:
                backfill.append(record)

        return lookback, backfill
