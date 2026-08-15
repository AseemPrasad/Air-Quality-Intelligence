"""Data quality validator and classification."""

import logging
from typing import Dict, List, Tuple, Any

from aq_engine.quality.rules import (
    AQStructuralValidation,
    AQSemanticValidation,
    AQTemporalValidation,
    AQOutlierValidation,
    AQStaleValidation,
    WeatherStructuralValidation,
    WeatherSemanticValidation,
    WeatherTemporalValidation,
)


logger = logging.getLogger(__name__)


class QualityValidator:
    """Validates records and classifies quality.

    Quality classes:
    - VALID: passes all hard checks, no warnings
    - SUSPICIOUS: passes hard checks but has warnings
    - INVALID: fails hard check
    """

    # Quality class constants
    VALID = "VALID"
    SUSPICIOUS = "SUSPICIOUS"
    INVALID = "INVALID"

    def __init__(self):
        """Initialize validator with all rules."""
        # Air quality rules
        self.aq_rules = [
            AQStructuralValidation(),
            AQSemanticValidation(),
            AQTemporalValidation(future_tolerance_hours=1.0),
            AQOutlierValidation(z_threshold=6.0),
            AQStaleValidation(flatline_threshold=3),
        ]

        # Weather rules
        self.weather_rules = [
            WeatherStructuralValidation(),
            WeatherSemanticValidation(),
            WeatherTemporalValidation(future_tolerance_hours=1.0),
        ]

    def validate_air_quality(self, record: dict) -> Tuple[str, List[str]]:
        """Validate air quality record.

        Args:
            record: Air quality record dict.

        Returns:
            Tuple of (quality_class, warnings).
            - quality_class: VALID, SUSPICIOUS, or INVALID
            - warnings: List of warning messages
        """
        all_warnings = []
        is_valid = True

        for rule in self.aq_rules:
            valid, warnings = rule.validate(record)

            if not valid:
                is_valid = False
                all_warnings.extend(warnings)
                break  # Stop on first hard failure

            all_warnings.extend(warnings)

        if not is_valid:
            return self.INVALID, all_warnings

        if all_warnings:
            return self.SUSPICIOUS, all_warnings

        return self.VALID, []

    def validate_weather(self, record: dict) -> Tuple[str, List[str]]:
        """Validate weather record.

        Args:
            record: Weather record dict.

        Returns:
            Tuple of (quality_class, warnings).
        """
        all_warnings = []
        is_valid = True

        for rule in self.weather_rules:
            valid, warnings = rule.validate(record)

            if not valid:
                is_valid = False
                all_warnings.extend(warnings)
                break

            all_warnings.extend(warnings)

        if not is_valid:
            return self.INVALID, all_warnings

        if all_warnings:
            return self.SUSPICIOUS, all_warnings

        return self.VALID, []

    def validate_batch(
        self,
        records: List[dict],
        source_type: str = "air_quality",
    ) -> Dict[str, Any]:
        """Validate batch of records.

        Args:
            records: List of records to validate.
            source_type: "air_quality" or "weather".

        Returns:
            Dict with:
            - VALID: count of valid records
            - SUSPICIOUS: count of suspicious records
            - INVALID: count of invalid records
            - invalid_records: list of (record, reasons) tuples
            - suspicious_records: list of (record, warnings) tuples
        """
        validator_func = (
            self.validate_air_quality if source_type == "air_quality" else self.validate_weather
        )

        result = {
            self.VALID: 0,
            self.SUSPICIOUS: 0,
            self.INVALID: 0,
            "invalid_records": [],
            "suspicious_records": [],
        }

        for record in records:
            quality_class, messages = validator_func(record)

            if quality_class == self.VALID:
                result[self.VALID] += 1
            elif quality_class == self.SUSPICIOUS:
                result[self.SUSPICIOUS] += 1
                result["suspicious_records"].append((record, messages))
            else:  # INVALID
                result[self.INVALID] += 1
                result["invalid_records"].append((record, messages))

            logger.debug(f"Record validated: {quality_class} ({', '.join(messages)})")

        return result
