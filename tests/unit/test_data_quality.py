"""Unit tests for data quality validation.

Tests validation rules, quality classification, and batch processing.
"""

import pytest
from datetime import datetime, timezone, timedelta

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


@pytest.fixture
def valid_aq_record():
    """Valid air quality record."""
    return {
        "source": "openaq",
        "station_id": "123",
        "sensor_id": "456",
        "pollutant": "pm25",
        "value": 45.5,
        "unit": "µg/m³",
        "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
        "raw_payload_hash": "abc123def456",
    }


@pytest.fixture
def valid_weather_record():
    """Valid weather record."""
    return {
        "source": "open_meteo",
        "location_id": "123",
        "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        "temperature_c": 28.5,
        "humidity_pct": 65.0,
        "wind_speed_kmh": 8.5,
        "wind_direction_deg": 180.0,
        "pressure_hpa": 1013.0,
        "precipitation_mm": 0.1,
        "cloud_cover_pct": 40.0,
        "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
        "raw_payload_hash": "xyz789",
    }


class TestAirQualityStructural:
    """Test structural validation for air quality."""

    def test_valid_record_passes(self, valid_aq_record):
        """Test valid record passes structural validation."""
        rule = AQStructuralValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True

    def test_missing_required_field_fails(self, valid_aq_record):
        """Test missing required field fails."""
        del valid_aq_record["station_id"]
        rule = AQStructuralValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is False
        assert "Missing required field" in warnings[0]

    def test_null_required_field_fails(self, valid_aq_record):
        """Test null required field fails."""
        valid_aq_record["value"] = None
        rule = AQStructuralValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is False

    def test_invalid_value_type_fails(self, valid_aq_record):
        """Test invalid value type fails."""
        valid_aq_record["value"] = "not_a_number"
        rule = AQStructuralValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is False
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_value_fails(self, valid_aq_record, value):
        """Test non-finite pollutant values fail structural validation."""
        valid_aq_record["value"] = value
        rule = AQStructuralValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is False
        assert "finite" in warnings[0].lower()

class TestAirQualitySemantic:
    """Test semantic validation for air quality."""

    def test_negative_value_fails(self, valid_aq_record):
        """Test negative pollutant value fails."""
        valid_aq_record["value"] = -5.0
        rule = AQSemanticValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is False
        assert "non-negative" in warnings[0].lower()

    def test_unknown_unit_warns(self, valid_aq_record):
        """Test unknown unit generates warning."""
        valid_aq_record["unit"] = "unknown_unit"
        rule = AQSemanticValidation()
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True
        assert len(warnings) > 0
        assert "Unknown unit" in warnings[0]


class TestAirQualityTemporal:
    """Test temporal validation for air quality."""

    def test_current_timestamp_passes(self, valid_aq_record):
        """Test current timestamp passes."""
        valid_aq_record["observed_at"] = datetime.now(timezone.utc)
        rule = AQTemporalValidation(future_tolerance_hours=1.0)
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True

    def test_future_timestamp_within_tolerance_passes(self, valid_aq_record):
        """Test future timestamp within tolerance passes."""
        valid_aq_record["observed_at"] = datetime.now(timezone.utc) + timedelta(minutes=30)
        rule = AQTemporalValidation(future_tolerance_hours=1.0)
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True

    def test_future_timestamp_beyond_tolerance_fails(self, valid_aq_record):
        """Test future timestamp beyond tolerance fails."""
        valid_aq_record["observed_at"] = datetime.now(timezone.utc) + timedelta(hours=2)
        rule = AQTemporalValidation(future_tolerance_hours=1.0)
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is False
        assert "future" in warnings[0].lower()


class TestAirQualityOutlier:
    """Test outlier detection for air quality."""

    def test_extreme_value_warns(self, valid_aq_record):
        """Test extreme value generates warning."""
        valid_aq_record["value"] = 1000.0  # Extremely high
        rule = AQOutlierValidation(z_threshold=6.0)
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True
        assert len(warnings) > 0
        assert "outlier" in warnings[0].lower()

    def test_normal_value_no_warning(self, valid_aq_record):
        """Test normal value doesn't warn."""
        valid_aq_record["value"] = 45.5
        rule = AQOutlierValidation(z_threshold=6.0)
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True
        assert len(warnings) == 0


class TestAirQualityStale:
    """Test stale data detection for air quality."""

    def test_round_number_warns(self, valid_aq_record):
        """Test suspiciously round number warns."""
        valid_aq_record["value"] = 50.0
        rule = AQStaleValidation(flatline_threshold=3)
        valid, warnings = rule.validate(valid_aq_record)
        assert valid is True
        assert len(warnings) > 0


class TestWeatherStructural:
    """Test structural validation for weather."""

    def test_valid_record_passes(self, valid_weather_record):
        """Test valid record passes."""
        rule = WeatherStructuralValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is True

    def test_missing_required_field_fails(self, valid_weather_record):
        """Test missing required field fails."""
        del valid_weather_record["temperature_c"]
        rule = WeatherStructuralValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False

    @pytest.mark.parametrize("field", ["temperature_c", "humidity_pct"])
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_required_values_fail(
        self, valid_weather_record, field, value
    ):
        """Test non-finite required weather values fail."""
        valid_weather_record[field] = value
        rule = WeatherStructuralValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False
        assert "finite" in warnings[0].lower()

class TestWeatherSemantic:
    """Test semantic validation for weather."""

    def test_humidity_above_100_fails(self, valid_weather_record):
        """Test humidity > 100% fails."""
        valid_weather_record["humidity_pct"] = 105.0
        rule = WeatherSemanticValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False

    def test_humidity_below_0_fails(self, valid_weather_record):
        """Test humidity < 0% fails."""
        valid_weather_record["humidity_pct"] = -5.0
        rule = WeatherSemanticValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False

    def test_temperature_extreme_fails(self, valid_weather_record):
        """Test extreme temperature fails."""
        valid_weather_record["temperature_c"] = 100.0
        rule = WeatherSemanticValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False

    def test_wind_direction_above_360_fails(self, valid_weather_record):
        """Test wind direction > 360° fails."""
        valid_weather_record["wind_direction_deg"] = 361.0
        rule = WeatherSemanticValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False

    def test_negative_wind_speed_fails(self, valid_weather_record):
        """Test negative wind speed fails."""
        valid_weather_record["wind_speed_kmh"] = -5.0
        rule = WeatherSemanticValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False

    @pytest.mark.parametrize(
        "field",
        [
            "wind_direction_deg",
            "wind_speed_kmh",
            "pressure_hpa",
            "precipitation_mm",
        ],
    )
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_optional_values_fail(
        self, valid_weather_record, field, value
    ):
        """Test non-finite optional weather values fail."""
        valid_weather_record[field] = value
        rule = WeatherSemanticValidation()
        valid, warnings = rule.validate(valid_weather_record)
        assert valid is False
        assert "finite" in warnings[0].lower()

class TestQualityValidator:
    """Test quality validator and classification."""

    def test_valid_aq_record_classified_valid(self, valid_aq_record):
        """Test valid record classified as VALID."""
        validator = QualityValidator()
        quality_class, warnings = validator.validate_air_quality(valid_aq_record)
        assert quality_class == QualityValidator.VALID
        assert len(warnings) == 0

    def test_invalid_aq_record_classified_invalid(self, valid_aq_record):
        """Test invalid record classified as INVALID."""
        valid_aq_record["value"] = -5.0
        validator = QualityValidator()
        quality_class, warnings = validator.validate_air_quality(valid_aq_record)
        assert quality_class == QualityValidator.INVALID

    def test_suspicious_aq_record_classified_suspicious(self, valid_aq_record):
        """Test suspicious record classified as SUSPICIOUS."""
        valid_aq_record["value"] = 50.0  # Round number (potential flatline)
        validator = QualityValidator()
        quality_class, warnings = validator.validate_air_quality(valid_aq_record)
        assert quality_class == QualityValidator.SUSPICIOUS
        assert len(warnings) > 0

    def test_valid_weather_record_classified_valid(self, valid_weather_record):
        """Test valid weather record classified as VALID."""
        validator = QualityValidator()
        quality_class, warnings = validator.validate_weather(valid_weather_record)
        assert quality_class == QualityValidator.VALID

    def test_invalid_weather_record_classified_invalid(self, valid_weather_record):
        """Test invalid weather record classified as INVALID."""
        valid_weather_record["humidity_pct"] = 105.0
        validator = QualityValidator()
        quality_class, warnings = validator.validate_weather(valid_weather_record)
        assert quality_class == QualityValidator.INVALID


class TestBatchValidation:
    """Test batch validation."""

    def test_batch_validation_counts_all_classes(self, valid_aq_record):
        """Test batch validation counts all quality classes."""
        records = [
            valid_aq_record,  # Valid
            {**valid_aq_record, "value": -5.0},  # Invalid
            {**valid_aq_record, "value": 50.0},  # Suspicious
        ]

        validator = QualityValidator()
        result = validator.validate_batch(records, source_type="air_quality")

        assert result[QualityValidator.VALID] == 1
        assert result[QualityValidator.INVALID] == 1
        assert result[QualityValidator.SUSPICIOUS] == 1
        assert len(result["invalid_records"]) == 1
        assert len(result["suspicious_records"]) == 1

    def test_batch_validation_captures_invalid_records(self, valid_aq_record):
        """Test batch validation captures invalid records."""
        invalid_record = {**valid_aq_record, "value": -5.0}
        records = [valid_aq_record, invalid_record]

        validator = QualityValidator()
        result = validator.validate_batch(records, source_type="air_quality")

        assert len(result["invalid_records"]) == 1
        captured_record, reasons = result["invalid_records"][0]
        assert captured_record["value"] == -5.0
        assert len(reasons) > 0


class TestEdgeCases:
    """Test edge cases."""

    def test_none_values_handled_gracefully(self, valid_aq_record):
        """Test None values in optional fields."""
        valid_aq_record["wind_speed_kmh"] = None
        validator = QualityValidator()
        quality_class, warnings = validator.validate_air_quality(valid_aq_record)
        # Should pass (field not required)
        assert quality_class in [QualityValidator.VALID, QualityValidator.SUSPICIOUS]

    def test_zero_value_passes(self, valid_aq_record):
        """Test zero value passes (not negative)."""
        valid_aq_record["value"] = 0.0
        validator = QualityValidator()
        quality_class, warnings = validator.validate_air_quality(valid_aq_record)
        assert quality_class in [QualityValidator.VALID, QualityValidator.SUSPICIOUS]


class TestAirQualityOutlierThreshold:
    """Regression tests for AQOutlierValidation.z_threshold.

    Prior to the fix, self.z_threshold was stored but never used.
    validate() applied hardcoded absolute bounds regardless of the configured
    threshold, making the parameter silently non-functional.

    These tests verify that z_threshold now controls the effective bound
    proportionally: bound = BASE_BOUND * (z_threshold / 6.0).
    """

    def test_high_threshold_suppresses_outlier_warning(self):
        """A very high z_threshold must suppress a warning that default fires.

        This test FAILED against upstream/main (threshold was ignored).
        """
        rule = AQOutlierValidation(z_threshold=999.0)
        record = {"value": 501.0, "pollutant": "pm25", "unit": "µg/m³"}
        valid, warnings = rule.validate(record)
        assert valid is True
        assert len(warnings) == 0, (
            f"z_threshold=999 should suppress outlier for value=501, got: {warnings}"
        )

    def test_low_threshold_flags_value_default_would_pass(self):
        """A tight z_threshold must flag a value that default (6.0) would not warn on."""
        # At z_threshold=3.0: effective pm25 bound = 500 * (3/6) = 250
        rule = AQOutlierValidation(z_threshold=3.0)
        record = {"value": 251.0, "pollutant": "pm25", "unit": "µg/m³"}
        valid, warnings = rule.validate(record)
        assert valid is True  # still not hard-invalid
        assert len(warnings) > 0, (
            "z_threshold=3.0 should flag value=251 (effective bound=250)"
        )

    def test_default_threshold_behavior_unchanged(self):
        """z_threshold=6.0 (default) must preserve the original behavior."""
        rule = AQOutlierValidation(z_threshold=6.0)

        # Above the 500 bound: must warn
        _, warnings_above = rule.validate({"value": 501.0, "pollutant": "pm25", "unit": "µg/m³"})
        assert len(warnings_above) > 0

        # Below the 500 bound: must not warn
        _, warnings_below = rule.validate({"value": 499.0, "pollutant": "pm25", "unit": "µg/m³"})
        assert len(warnings_below) == 0

    def test_different_thresholds_produce_different_results(self):
        """Two different thresholds must not produce identical output for a boundary value."""
        record = {"value": 300.0, "pollutant": "pm25", "unit": "µg/m³"}

        # z_threshold=3.0 → bound=250 → 300 > 250 → warns
        _, w_tight = AQOutlierValidation(z_threshold=3.0).validate(record)
        # z_threshold=6.0 → bound=500 → 300 < 500 → no warning
        _, w_default = AQOutlierValidation(z_threshold=6.0).validate(record)

        assert len(w_tight) > 0
        assert len(w_default) == 0

    def test_unknown_pollutant_never_warns_regardless_of_threshold(self):
        """Records with an unknown pollutant must never trigger outlier warnings."""
        for threshold in [1.0, 6.0, 999.0]:
            rule = AQOutlierValidation(z_threshold=threshold)
            _, warnings = rule.validate({"value": 99999.0, "pollutant": "unknown_gas"})
            assert len(warnings) == 0, f"threshold={threshold} should not warn for unknown pollutant"

    def test_none_value_no_warning_regardless_of_threshold(self):
        """None value must never produce a warning."""
        rule = AQOutlierValidation(z_threshold=0.01)
        _, warnings = rule.validate({"value": None, "pollutant": "pm25"})
        assert len(warnings) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
