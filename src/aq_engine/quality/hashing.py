"""Measurement key generation for idempotency and deduplication.

Computes deterministic SHA256 hashes for identifying duplicate observations.
"""

import hashlib
from datetime import datetime
from typing import Union

from aq_engine.common import ensure_utc


def generate_measurement_key(
    source: str,
    station_id: str,
    sensor_id: str,
    pollutant: str,
    observed_at: Union[datetime, str],
) -> str:
    """Generate deterministic SHA256 measurement key.

    The measurement key uniquely identifies an observation by:
    - Data source (e.g., "openaq")
    - Station/location (e.g., "123")
    - Sensor (e.g., "456")
    - Pollutant (e.g., "pm25")
    - Observation time (exact timestamp, UTC)

    This key is used for:
    - Idempotency (same key = same observation)
    - Deduplication (detect duplicate ingestions)
    - Database lookups (find existing records)

    Args:
        source: Source identifier.
        station_id: Station/location ID.
        sensor_id: Sensor ID.
        pollutant: Pollutant code.
        observed_at: Observation timestamp (datetime or ISO 8601 string).

    Returns:
        SHA256 hex string (64 characters).

    Example:
        >>> key = generate_measurement_key(
        ...     source="openaq",
        ...     station_id="123",
        ...     sensor_id="456",
        ...     pollutant="pm25",
        ...     observed_at="2026-08-15T12:00:00Z"
        ... )
        >>> # key = "abc123def456..."
    """
    # Normalize timestamp to UTC ISO format
    if isinstance(observed_at, str):
        # Parse ISO 8601 string
        dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        dt = ensure_utc(dt)
        timestamp_str = dt.isoformat()
    else:
        # Ensure datetime is UTC
        dt = ensure_utc(observed_at)
        timestamp_str = dt.isoformat()

    # Build measurement key components
    # Format: source|station_id|sensor_id|pollutant|timestamp
    components = [
        str(source).lower().strip(),
        str(station_id).strip(),
        str(sensor_id).strip(),
        str(pollutant).lower().strip(),
        timestamp_str,
    ]

    key_string = "|".join(components)

    # Compute SHA256 hash
    key_hash = hashlib.sha256(key_string.encode()).hexdigest()

    return key_hash


def generate_weather_key(
    source: str,
    location_id: str,
    observed_at: Union[datetime, str],
) -> str:
    """Generate deterministic SHA256 key for weather observation.

    Similar to measurement_key but for weather data (fewer dimensions).

    The key uniquely identifies weather by:
    - Data source (e.g., "open_meteo")
    - Location (e.g., "123")
    - Observation time (exact timestamp, UTC)

    Args:
        source: Source identifier.
        location_id: Location/station ID.
        observed_at: Observation timestamp (datetime or ISO 8601 string).

    Returns:
        SHA256 hex string (64 characters).

    Example:
        >>> key = generate_weather_key(
        ...     source="open_meteo",
        ...     location_id="123",
        ...     observed_at="2026-08-15T12:00:00Z"
        ... )
        >>> # key = "xyz789abc012..."
    """
    # Normalize timestamp to UTC ISO format
    if isinstance(observed_at, str):
        dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        dt = ensure_utc(dt)
        timestamp_str = dt.isoformat()
    else:
        dt = ensure_utc(observed_at)
        timestamp_str = dt.isoformat()

    # Build key components
    # Format: source|location_id|timestamp
    components = [
        str(source).lower().strip(),
        str(location_id).strip(),
        timestamp_str,
    ]

    key_string = "|".join(components)

    # Compute SHA256 hash
    key_hash = hashlib.sha256(key_string.encode()).hexdigest()

    return key_hash
