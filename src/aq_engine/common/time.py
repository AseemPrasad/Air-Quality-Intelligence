"""Time utilities for the Air Quality Intelligence Platform.

Handles timezone conversions, UTC validation, partitioning, and temporal checks
with comprehensive edge-case handling for DST, future dates, and timezone awareness.
"""

from datetime import datetime, timedelta, timezone
import pytz


# IST (Indian Standard Time) timezone
IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC


def ensure_utc(dt: datetime) -> datetime:
    """Convert datetime to UTC, ensuring timezone awareness.

    Handles:
    - Naive datetimes (assumed to be UTC)
    - Timezone-aware datetimes (converted to UTC)
    - Invalid datetimes (raises ValueError)

    Args:
        dt: datetime object (naive or aware).

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        TypeError: If dt is not a datetime object.
        ValueError: If dt is far outside reasonable bounds.

    Example:
        >>> dt_naive = datetime(2026, 8, 15, 12, 0, 0)
        >>> ensure_utc(dt_naive)
        datetime.datetime(2026, 8, 15, 12, 0, 0, tzinfo=tzutc())

        >>> dt_ist = IST.localize(datetime(2026, 8, 15, 12, 0, 0))
        >>> ensure_utc(dt_ist)
        datetime.datetime(2026, 8, 15, 6, 30, 0, tzinfo=tzutc())
    """
    if not isinstance(dt, datetime):
        raise TypeError(f"Expected datetime, got {type(dt).__name__}")

    # Sanity check: datetime should be within 200 years of now
    now = datetime.now(UTC)
    if abs((dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt) - now) > timedelta(days=200 * 365):
        raise ValueError(f"DateTime {dt} is outside reasonable bounds")

    if dt.tzinfo is None:
        # Naive datetime: assume UTC
        return dt.replace(tzinfo=UTC)
    else:
        # Aware datetime: convert to UTC
        return dt.astimezone(UTC)


def to_ist(dt: datetime) -> datetime:
    """Convert datetime to IST (Asia/Kolkata).

    Args:
        dt: datetime object (naive or aware).

    Returns:
        Timezone-aware datetime in IST.

    Raises:
        TypeError: If dt is not a datetime object.
    """
    if not isinstance(dt, datetime):
        raise TypeError(f"Expected datetime, got {type(dt).__name__}")

    utc_dt = ensure_utc(dt)
    return utc_dt.astimezone(IST)


def round_to_hour(dt: datetime, direction: str = "floor") -> datetime:
    """Round datetime to hour boundary.

    Args:
        dt: datetime object.
        direction: "floor" (down to hour start) or "ceil" (up to next hour).

    Returns:
        Datetime with minutes/seconds/microseconds set to 0 (floor) or hour+1 (ceil).

    Raises:
        ValueError: If direction is not "floor" or "ceil".

    Example:
        >>> dt = datetime(2026, 8, 15, 12, 35, 45, tzinfo=UTC)
        >>> round_to_hour(dt, "floor")
        datetime.datetime(2026, 8, 15, 12, 0, 0, tzinfo=tzutc())
        >>> round_to_hour(dt, "ceil")
        datetime.datetime(2026, 8, 15, 13, 0, 0, tzinfo=tzutc())
    """
    if direction not in ("floor", "ceil"):
        raise ValueError(f"direction must be 'floor' or 'ceil', got {direction}")

    dt = ensure_utc(dt)
    floored = dt.replace(minute=0, second=0, microsecond=0)

    if direction == "floor":
        return floored
    else:  # ceil
        if floored == dt:
            return floored
        else:
            return floored + timedelta(hours=1)


def is_future(dt: datetime, tolerance_hours: float = 0) -> bool:
    """Check if datetime is in the future relative to now.

    Args:
        dt: datetime to check.
        tolerance_hours: Allow dates up to N hours in the future (e.g., clock skew).

    Returns:
        True if dt is beyond (now + tolerance_hours).

    Example:
        >>> future = datetime.now(UTC) + timedelta(hours=2)
        >>> is_future(future, tolerance_hours=1)
        True
        >>> is_future(future, tolerance_hours=3)
        False
    """
    dt = ensure_utc(dt)
    now = datetime.now(UTC)
    threshold = now + timedelta(hours=tolerance_hours)
    return dt > threshold


def date_partition_path(dt: datetime) -> str:
    """Generate partition path for data storage.

    Returns Parquet partition-like path: "year=YYYY/month=MM/day=DD"

    Args:
        dt: datetime object.

    Returns:
        Partition path string.

    Example:
        >>> dt = datetime(2026, 8, 15, 12, 30, 0, tzinfo=UTC)
        >>> date_partition_path(dt)
        'year=2026/month=08/day=15'
    """
    dt = ensure_utc(dt)
    return f"year={dt.year:04d}/month={dt.month:02d}/day={dt.day:02d}"


def hour_partition_path(dt: datetime) -> str:
    """Generate partition path with hour granularity.

    Returns Parquet partition-like path: "year=YYYY/month=MM/day=DD/hour=HH"

    Args:
        dt: datetime object.

    Returns:
        Partition path string including hour.

    Example:
        >>> dt = datetime(2026, 8, 15, 12, 30, 0, tzinfo=UTC)
        >>> hour_partition_path(dt)
        'year=2026/month=08/day=15/hour=12'
    """
    dt = ensure_utc(dt)
    return f"year={dt.year:04d}/month={dt.month:02d}/day={dt.day:02d}/hour={dt.hour:02d}"


def get_date_range(start: datetime, end: datetime) -> list[datetime]:
    """Generate list of midnight (00:00 UTC) for each day in range [start, end].

    Useful for iterating over daily partitions.

    Args:
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        List of datetime objects at 00:00 UTC for each day.

    Raises:
        ValueError: If start > end.

    Example:
        >>> start = datetime(2026, 8, 13, tzinfo=UTC)
        >>> end = datetime(2026, 8, 15, tzinfo=UTC)
        >>> dates = get_date_range(start, end)
        >>> len(dates)
        3
    """
    start = ensure_utc(start).replace(hour=0, minute=0, second=0, microsecond=0)
    end = ensure_utc(end).replace(hour=0, minute=0, second=0, microsecond=0)

    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)

    return dates


def get_hour_range(start: datetime, end: datetime) -> list[datetime]:
    """Generate list of hourly boundaries [start, end].

    Useful for iterating over hourly partitions or time windows.

    Args:
        start: Start time (inclusive).
        end: End time (inclusive).

    Returns:
        List of datetime objects at each hour boundary.

    Raises:
        ValueError: If start > end.

    Example:
        >>> start = datetime(2026, 8, 15, 10, 0, 0, tzinfo=UTC)
        >>> end = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
        >>> hours = get_hour_range(start, end)
        >>> len(hours)
        3
    """
    start = ensure_utc(start).replace(minute=0, second=0, microsecond=0)
    end = ensure_utc(end).replace(minute=0, second=0, microsecond=0)

    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    hours = []
    current = start
    while current <= end:
        hours.append(current)
        current += timedelta(hours=1)

    return hours


def timestamp_iso8601(dt: datetime) -> str:
    """Format datetime as ISO 8601 string.

    Args:
        dt: datetime object.

    Returns:
        ISO 8601 formatted string (with timezone).

    Example:
        >>> dt = datetime(2026, 8, 15, 12, 30, 45, tzinfo=UTC)
        >>> timestamp_iso8601(dt)
        '2026-08-15T12:30:45+00:00'
    """
    dt = ensure_utc(dt)
    return dt.isoformat()


def parse_iso8601(timestamp: str) -> datetime:
    """Parse ISO 8601 timestamp string to datetime.

    Handles multiple ISO 8601 formats:
    - 2026-08-15T12:30:45Z
    - 2026-08-15T12:30:45+00:00
    - 2026-08-15T12:30:45-05:00
    - 2026-08-15 12:30:45

    Args:
        timestamp: ISO 8601 formatted timestamp string.

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        ValueError: If timestamp cannot be parsed.

    Example:
        >>> dt = parse_iso8601("2026-08-15T12:30:45Z")
        >>> dt.tzinfo
        tzutc()
    """
    try:
        # Try Python's built-in fromisoformat (Python 3.11+)
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        try:
            # Fallback: try parsing with dateutil if available
            from dateutil.parser import parse as dateutil_parse

            dt = dateutil_parse(timestamp)
        except ImportError:
            raise ValueError(
                f"Cannot parse timestamp '{timestamp}'. Install python-dateutil for flexible parsing."
            )

    return ensure_utc(dt)


def days_ago(days: int) -> datetime:
    """Get datetime N days ago at midnight UTC.

    Args:
        days: Number of days ago (positive integer).

    Returns:
        datetime at 00:00 UTC N days ago.

    Example:
        >>> past = days_ago(7)  # One week ago
    """
    if days < 0:
        raise ValueError("days must be non-negative")

    ago = datetime.now(UTC) - timedelta(days=days)
    return ago.replace(hour=0, minute=0, second=0, microsecond=0)


def hours_ago(hours: int) -> datetime:
    """Get datetime N hours ago.

    Args:
        hours: Number of hours ago (positive integer).

    Returns:
        datetime N hours ago.

    Example:
        >>> past = hours_ago(6)  # Six hours ago
    """
    if hours < 0:
        raise ValueError("hours must be non-negative")

    return datetime.now(UTC) - timedelta(hours=hours)
