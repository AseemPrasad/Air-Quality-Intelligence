"""Quality layer for data validation and storage.

Provides data contracts, hashing, validation rules, and quarantine handling.
"""

from aq_engine.quality.contracts import RawAirQualityRecord, RawWeatherRecord
from aq_engine.quality.hashing import generate_measurement_key, generate_weather_key
from aq_engine.quality.validator import QualityValidator
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
from aq_engine.quality.quarantine import QuarantineManager

__all__ = [
    "RawAirQualityRecord",
    "RawWeatherRecord",
    "generate_measurement_key",
    "generate_weather_key",
    "QualityValidator",
    "AQStructuralValidation",
    "AQSemanticValidation",
    "AQTemporalValidation",
    "AQOutlierValidation",
    "AQStaleValidation",
    "WeatherStructuralValidation",
    "WeatherSemanticValidation",
    "WeatherTemporalValidation",
    "QuarantineManager",
]
