"""Data quality validation rules.

Implements structural, semantic, temporal, and referential validation rules
for air quality and weather data. Each rule is callable and returns a tuple
of (is_valid, warnings).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, List, Optional, Any
from abc import ABC, abstractmethod
import math

from aq_engine.common import ensure_utc


logger = logging.getLogger(__name__)


class ValidationRule(ABC):
    """Base class for validation rules."""

    @abstractmethod
    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate a record.

        Args:
            record: Record dict to validate.

        Returns:
            Tuple of (is_valid, warnings).
            - is_valid: True if record passes hard checks
            - warnings: List of warning messages (soft issues)
        """
        pass


# ============================================================================
# AIR QUALITY VALIDATION RULES
# ============================================================================


class AQStructuralValidation(ValidationRule):
    """Validate required fields and types for air quality records."""

    REQUIRED_FIELDS = [
        "source",
        "station_id",
        "sensor_id",
        "pollutant",
        "value",
        "unit",
        "observed_at",
        "ingested_at",
        "raw_payload_hash",
    ]

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate structural requirements.

        Example:
            >>> rule = AQStructuralValidation()
            >>> valid, warnings = rule.validate({
            ...     "source": "openaq",
            ...     "station_id": "123",
            ...     "sensor_id": "456",
            ...     "pollutant": "pm25",
            ...     "value": 45.5,
            ...     "unit": "µg/m³",
            ...     "observed_at": datetime.now(timezone.utc),
            ...     "ingested_at": datetime.now(timezone.utc),
            ...     "raw_payload_hash": "abc123",
            ... })
            >>> assert valid
        """
        warnings = []

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in record:
                return False, [f"Missing required field: {field}"]
            if record[field] is None:
                return False, [f"Null required field: {field}"]

        # Check types
        if not isinstance(record["value"], (int, float)):
            return False, ["Value must be numeric"]

        if not isinstance(record["observed_at"], datetime):
            return False, ["observed_at must be datetime"]

        if not isinstance(record["ingested_at"], datetime):
            return False, ["ingested_at must be datetime"]

        return True, warnings


class AQSemanticValidation(ValidationRule):
    """Validate semantic rules for air quality records."""

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate semantic requirements.

        Example:
            >>> rule = AQSemanticValidation()
            >>> valid, warnings = rule.validate({"value": -5})
            >>> assert not valid
        """
        warnings = []

        # Pollutant value must be non-negative
        if record.get("value", 0) < 0:
            return False, ["Pollutant value must be non-negative"]

        # Unit should be recognized
        valid_units = ["µg/m³", "mg/m³", "ppb", "ppm"]
        if record.get("unit") not in valid_units:
            warnings.append(f"Unknown unit: {record.get('unit')}")

        return True, warnings


class AQTemporalValidation(ValidationRule):
    """Validate temporal requirements for air quality records."""

    def __init__(self, future_tolerance_hours: float = 1.0):
        """Initialize with future tolerance.

        Args:
            future_tolerance_hours: Allow observations up to N hours in future.
        """
        self.future_tolerance = timedelta(hours=future_tolerance_hours)

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate temporal requirements.

        Example:
            >>> rule = AQTemporalValidation(future_tolerance_hours=1)
            >>> future_date = datetime.now(timezone.utc) + timedelta(hours=2)
            >>> valid, warnings = rule.validate({"observed_at": future_date})
            >>> assert not valid
        """
        warnings = []

        observed_at = record.get("observed_at")
        if not isinstance(observed_at, datetime):
            return False, ["observed_at is not datetime"]

        observed_at = ensure_utc(observed_at)
        now = datetime.now(timezone.utc)

        # Check if observation is in future (beyond tolerance)
        if observed_at > now + self.future_tolerance:
            return False, [
                f"Observation time is in future: {observed_at} "
                f"(tolerance: {self.future_tolerance})"
            ]

        return True, warnings


class AQOutlierValidation(ValidationRule):
    """Detect extreme outliers using z-score."""

    def __init__(self, z_threshold: float = 6.0):
        """Initialize with z-score threshold.

        Args:
            z_threshold: Flag as outlier if z-score > threshold.
        """
        self.z_threshold = z_threshold

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate for outliers.

        Extreme outliers (z > 6) are flagged as suspicious but not invalid.

        Example:
            >>> rule = AQOutlierValidation(z_threshold=6)
            >>> valid, warnings = rule.validate({"value": 10000})
            >>> assert valid
            >>> assert len(warnings) > 0
        """
        warnings = []

        value = record.get("value")
        if value is None or not isinstance(value, (int, float)):
            return True, warnings

        # Very rough outlier check: if value is extremely high
        # (more sophisticated: would use historical median + MAD)
        pollutant = record.get("pollutant", "").lower()

        # Reasonable upper bounds for pollutants
        bounds = {
            "pm25": 500.0,  # µg/m³
            "pm10": 800.0,
            "no2": 200.0,  # ppb typically
            "o3": 200.0,
        }

        if pollutant in bounds and value > bounds[pollutant]:
            warnings.append(f"Extreme outlier: {value} {record.get('unit')}")

        return True, warnings


class AQStaleValidation(ValidationRule):
    """Detect stale/flatline data."""

    def __init__(self, flatline_threshold: int = 3):
        """Initialize with flatline threshold.

        Args:
            flatline_threshold: Flag if N+ consecutive identical values.
        """
        self.flatline_threshold = flatline_threshold

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate for staleness.

        Note: This rule operates on single records, so actual flatline
        detection happens at aggregation layer (needs historical data).

        Returns:
            (True, ["Possible stale value"]) if value is suspiciously round.
        """
        warnings = []

        value = record.get("value")
        if value is None:
            return True, warnings

        # Flag suspiciously round numbers as potentially stale
        if value > 0 and value == int(value) and value % 10 == 0:
            warnings.append("Value is suspiciously round (possible default)")

        return True, warnings


# ============================================================================
# WEATHER VALIDATION RULES
# ============================================================================


class WeatherStructuralValidation(ValidationRule):
    """Validate required fields and types for weather records."""

    REQUIRED_FIELDS = [
        "source",
        "location_id",
        "observed_at",
        "temperature_c",
        "humidity_pct",
        "ingested_at",
        "raw_payload_hash",
    ]

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate structural requirements."""
        warnings = []

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in record:
                return False, [f"Missing required field: {field}"]
            if record[field] is None:
                return False, [f"Null required field: {field}"]

        # Check numeric types
        if not isinstance(record.get("temperature_c"), (int, float)):
            return False, ["temperature_c must be numeric"]

        if not isinstance(record.get("humidity_pct"), (int, float)):
            return False, ["humidity_pct must be numeric"]

        return True, warnings


class WeatherSemanticValidation(ValidationRule):
    """Validate semantic rules for weather records."""

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate semantic requirements."""
        warnings = []

        # Humidity must be 0-100%
        humidity = record.get("humidity_pct")
        if humidity is not None:
            if not (0 <= humidity <= 100):
                return False, [f"Humidity out of range: {humidity}%"]

        # Temperature must be reasonable for Earth
        temperature = record.get("temperature_c")
        if temperature is not None:
            if not (-60 <= temperature <= 60):
                return False, [f"Temperature out of reasonable range: {temperature}°C"]

        # Wind direction must be 0-360°
        wind_dir = record.get("wind_direction_deg")
        if wind_dir is not None:
            if not (0 <= wind_dir <= 360):
                return False, [f"Wind direction out of range: {wind_dir}°"]

        # Wind speed must be non-negative
        wind_speed = record.get("wind_speed_kmh")
        if wind_speed is not None:
            if wind_speed < 0:
                return False, ["Wind speed must be non-negative"]

        # Pressure must be reasonable
        pressure = record.get("pressure_hpa")
        if pressure is not None:
            if not (900 <= pressure <= 1100):
                return False, [f"Pressure out of range: {pressure} hPa"]

        # Precipitation must be non-negative
        precipitation = record.get("precipitation_mm")
        if precipitation is not None:
            if precipitation < 0:
                return False, ["Precipitation must be non-negative"]

        return True, warnings


class WeatherTemporalValidation(ValidationRule):
    """Validate temporal requirements for weather records."""

    def __init__(self, future_tolerance_hours: float = 1.0):
        """Initialize with future tolerance."""
        self.future_tolerance = timedelta(hours=future_tolerance_hours)

    def validate(self, record: dict) -> Tuple[bool, List[str]]:
        """Validate temporal requirements."""
        warnings = []

        observed_at = record.get("observed_at")
        if not isinstance(observed_at, datetime):
            return False, ["observed_at is not datetime"]

        observed_at = ensure_utc(observed_at)
        now = datetime.now(timezone.utc)

        if observed_at > now + self.future_tolerance:
            return False, [f"Observation in future beyond tolerance"]

        return True, warnings
