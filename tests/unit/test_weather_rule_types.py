"""Regression tests for type handling in weather semantic validation."""

import pytest

from aq_engine.quality.rules import WeatherSemanticValidation


@pytest.fixture
def weather_record():
    return {
        "source": "open_meteo",
        "location_id": "kolkata",
        "temperature_c": 28.0,
        "humidity_pct": 70.0,
        "wind_speed_kmh": 10.0,
        "wind_direction_deg": 180.0,
        "pressure_hpa": 1010.0,
        "precipitation_mm": 0.0,
    }


@pytest.mark.parametrize(
    "field",
    [
        "temperature_c",
        "humidity_pct",
        "wind_speed_kmh",
        "wind_direction_deg",
        "pressure_hpa",
        "precipitation_mm",
    ],
)
@pytest.mark.parametrize("value", ["n/a", {}, [], True])
def test_non_numeric_optional_fields_are_invalid(weather_record, field, value):
    weather_record[field] = value

    valid, warnings = WeatherSemanticValidation().validate(weather_record)

    assert valid is False
    assert any("numeric" in warning.lower() for warning in warnings)


def test_valid_weather_record_still_passes(weather_record):
    valid, warnings = WeatherSemanticValidation().validate(weather_record)

    assert valid is True
    assert warnings == []
