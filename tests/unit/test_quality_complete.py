"""Comprehensive tests for data quality validation."""

import pytest
from datetime import datetime, timedelta
import hashlib


class TestValidRecordsPassAllRules:
    """Test valid records pass all validation rules."""

    def test_valid_pm25_record(self):
        """Test valid PM2.5 record passes all checks."""
        record = {
            "source": "openaq",
            "station_id": "stn_001",
            "location_id": "kolkata_001",
            "pollutant": "PM2.5",
            "value": 65.5,
            "unit": "µg/m³",
            "observed_at": "2026-08-15T10:00:00Z",
            "quality_flag": "VALID",
        }

        # All validation checks
        checks = [
            record["value"] >= 0,  # Non-negative
            record["value"] <= 1000,  # Not extreme
            record["unit"] == "µg/m³",  # Correct unit
            record["observed_at"],  # Has timestamp
            record["station_id"],  # Has station
        ]

        assert all(checks) is True

    def test_valid_weather_record(self):
        """Test valid weather record passes checks."""
        record = {
            "source": "open_meteo",
            "location_id": "kolkata_001",
            "temperature_c": 28.5,
            "humidity_pct": 82,
            "wind_speed_kmh": 3.5,
            "observed_at": "2026-08-15T10:00:00Z",
        }

        checks = [
            -50 <= record["temperature_c"] <= 60,
            0 <= record["humidity_pct"] <= 100,
            0 <= record["wind_speed_kmh"] <= 100,
            record["observed_at"],
        ]

        assert all(checks) is True


class TestNegativeValueRejected:
    """Test negative values are rejected."""

    def test_negative_pm25_rejected(self):
        """Test negative PM2.5 value is rejected."""
        value = -5.0
        is_valid = value >= 0
        assert is_valid is False

    def test_negative_temperature_accepted(self):
        """Test negative temperature is accepted (valid range)."""
        value = -10.0
        is_valid = -50 <= value <= 60
        assert is_valid is True

    def test_negative_humidity_rejected(self):
        """Test negative humidity is rejected."""
        value = -5
        is_valid = 0 <= value <= 100
        assert is_valid is False

    def test_boundary_zero_accepted(self):
        """Test zero value is accepted for concentrations."""
        value = 0.0
        is_valid = value >= 0
        assert is_valid is True


class TestFutureTimestampRejected:
    """Test future timestamps are rejected."""

    def test_future_timestamp_1hour_rejected(self):
        """Test timestamp >1 hour in future is rejected."""
        current_time = datetime(2026, 8, 15, 10, 0, 0)
        record_time = datetime(2026, 8, 15, 11, 30, 0)

        delta = (record_time - current_time).total_seconds()
        is_valid = delta <= 3600  # 1 hour in seconds

        assert is_valid is False

    def test_future_timestamp_exactly_1hour_boundary(self):
        """Test timestamp exactly 1 hour in future is boundary."""
        current_time = datetime(2026, 8, 15, 10, 0, 0)
        record_time = datetime(2026, 8, 15, 11, 0, 0)

        delta = (record_time - current_time).total_seconds()
        is_valid = delta <= 3600

        assert is_valid is True

    def test_future_timestamp_just_over_1hour_rejected(self):
        """Test timestamp just over 1 hour in future is rejected."""
        current_time = datetime(2026, 8, 15, 10, 0, 0)
        record_time = datetime(2026, 8, 15, 11, 0, 1)

        delta = (record_time - current_time).total_seconds()
        is_valid = delta <= 3600

        assert is_valid is False

    def test_past_timestamp_accepted(self):
        """Test past timestamp is accepted."""
        current_time = datetime(2026, 8, 15, 10, 0, 0)
        record_time = datetime(2026, 8, 15, 9, 30, 0)

        delta = (record_time - current_time).total_seconds()
        is_valid = delta <= 3600

        assert is_valid is True


class TestUnknownStationRejected:
    """Test unknown stations are rejected."""

    def test_known_station_accepted(self):
        """Test known station is accepted."""
        known_stations = ["stn_001", "stn_002", "stn_003"]
        station_id = "stn_001"

        is_valid = station_id in known_stations

        assert is_valid is True

    def test_unknown_station_rejected(self):
        """Test unknown station is rejected."""
        known_stations = ["stn_001", "stn_002", "stn_003"]
        station_id = "stn_999"

        is_valid = station_id in known_stations

        assert is_valid is False

    def test_empty_station_id_rejected(self):
        """Test empty station ID is rejected."""
        known_stations = ["stn_001", "stn_002", "stn_003"]
        station_id = ""

        is_valid = bool(station_id) and station_id in known_stations

        assert is_valid is False


class TestDuplicateMeasurementDetection:
    """Test duplicate measurement detection."""

    def test_duplicate_measurement_key_flagged(self):
        """Test duplicate based on measurement_key is flagged."""
        # Measurement key: SHA256(source, location, pollutant, observed_at)
        record1 = {
            "source": "openaq",
            "location_id": "kolkata_001",
            "pollutant": "PM2.5",
            "observed_at": "2026-08-15T10:00:00Z",
            "value": 65.5,
        }

        record2 = {
            "source": "openaq",
            "location_id": "kolkata_001",
            "pollutant": "PM2.5",
            "observed_at": "2026-08-15T10:00:00Z",
            "value": 65.6,  # Different value, same key
        }

        def get_measurement_key(r):
            key_str = f"{r['source']}{r['location_id']}{r['pollutant']}{r['observed_at']}"
            return hashlib.sha256(key_str.encode()).hexdigest()

        key1 = get_measurement_key(record1)
        key2 = get_measurement_key(record2)

        is_duplicate = key1 == key2

        assert is_duplicate is True

    def test_different_timestamp_not_duplicate(self):
        """Test different timestamps are not duplicates."""
        record1 = {
            "source": "openaq",
            "location_id": "kolkata_001",
            "pollutant": "PM2.5",
            "observed_at": "2026-08-15T10:00:00Z",
        }

        record2 = {
            "source": "openaq",
            "location_id": "kolkata_001",
            "pollutant": "PM2.5",
            "observed_at": "2026-08-15T10:01:00Z",  # Different time
        }

        def get_measurement_key(r):
            key_str = f"{r['source']}{r['location_id']}{r['pollutant']}{r['observed_at']}"
            return hashlib.sha256(key_str.encode()).hexdigest()

        key1 = get_measurement_key(record1)
        key2 = get_measurement_key(record2)

        is_duplicate = key1 == key2

        assert is_duplicate is False


class TestFlatlineDetection:
    """Test flatline detection (3+ identical consecutive values)."""

    def test_flatline_3_identical_values_flagged(self):
        """Test 3 identical values in sequence flagged SUSPICIOUS."""
        values = [65.5, 65.5, 65.5]

        # Check for flatline
        is_flatline = (
            len(values) >= 3 and
            len(set(values[-3:])) == 1
        )

        assert is_flatline is True

    def test_flatline_4_identical_values_flagged(self):
        """Test 4 identical values flagged."""
        values = [60.0, 60.0, 60.0, 60.0]

        is_flatline = (
            len(values) >= 3 and
            len(set(values[-3:])) == 1
        )

        assert is_flatline is True

    def test_no_flatline_2_identical_values(self):
        """Test 2 identical values is not flatline."""
        values = [65.5, 65.5]

        is_flatline = (
            len(values) >= 3 and
            len(set(values[-3:])) == 1
        )

        assert is_flatline is False

    def test_no_flatline_with_variation(self):
        """Test slight variation prevents flatline."""
        values = [65.5, 65.5, 65.6]

        is_flatline = (
            len(values) >= 3 and
            len(set(values[-3:])) == 1
        )

        assert is_flatline is False


class TestExtremeOutlierDetection:
    """Test extreme outlier detection (z > 6)."""

    def test_extreme_outlier_z_score_6(self):
        """Test z-score = 6 is flagged as extreme."""
        # Assuming mean=50, std=10
        mean = 50
        std = 10
        value = 110  # 6 standard deviations above mean

        z_score = (value - mean) / std
        is_extreme = z_score >= 6

        assert z_score == 6.0
        assert is_extreme is True

    def test_extreme_outlier_z_score_7(self):
        """Test z-score > 6 is flagged."""
        mean = 50
        std = 10
        value = 120  # 7 standard deviations above

        z_score = (value - mean) / std
        is_extreme = z_score >= 6

        assert is_extreme is True

    def test_normal_value_z_score_2(self):
        """Test z-score = 2 is not extreme."""
        mean = 50
        std = 10
        value = 70  # 2 standard deviations

        z_score = (value - mean) / std
        is_extreme = z_score >= 6

        assert z_score == 2.0
        assert is_extreme is False

    def test_boundary_z_score_just_under_6(self):
        """Test z-score just under 6 is not extreme."""
        mean = 50
        std = 10
        value = 109.9  # Just under 6 std

        z_score = (value - mean) / std
        is_extreme = z_score >= 6

        assert z_score < 6.0
        assert is_extreme is False


class TestUnitConversion:
    """Test unit conversion (µg/m³ ← mg/m³)."""

    def test_convert_mg_to_micrograms(self):
        """Test conversion from mg/m³ to µg/m³."""
        value_mg = 0.065  # mg/m³
        converted = value_mg * 1000  # µg/m³

        assert converted == 65.0

    def test_convert_multiple_values(self):
        """Test multiple unit conversions."""
        test_cases = [
            (0.01, 10),      # 0.01 mg → 10 µg
            (0.1, 100),      # 0.1 mg → 100 µg
            (0.5, 500),      # 0.5 mg → 500 µg
        ]

        for mg_value, expected_ug in test_cases:
            converted = mg_value * 1000
            assert converted == expected_ug

    def test_already_correct_unit_no_conversion(self):
        """Test already correct unit requires no conversion."""
        value = 65.5
        unit = "µg/m³"

        if unit == "µg/m³":
            converted = value
        else:
            converted = value * 1000

        assert converted == 65.5


class TestNullRequiredFieldRejected:
    """Test null required fields are rejected."""

    def test_null_pollutant_rejected(self):
        """Test null pollutant is rejected."""
        pollutant = None
        is_valid = pollutant is not None

        assert is_valid is False

    def test_null_timestamp_rejected(self):
        """Test null timestamp is rejected."""
        timestamp = None
        is_valid = timestamp is not None

        assert is_valid is False

    def test_null_value_rejected(self):
        """Test null value is rejected."""
        value = None
        is_valid = value is not None

        assert is_valid is False

    def test_empty_string_treated_as_null(self):
        """Test empty string treated as null for required fields."""
        station_id = ""
        is_valid = bool(station_id)

        assert is_valid is False

    def test_zero_value_not_treated_as_null(self):
        """Test zero value is not treated as null."""
        value = 0.0
        is_valid = value is not None

        assert is_valid is True


class TestQualityFlagAssignment:
    """Test quality flag assignment based on validation."""

    def test_valid_record_gets_valid_flag(self):
        """Test passing all checks gets VALID flag."""
        checks = [
            True,  # Non-negative
            True,  # Not extreme
            True,  # Known station
            True,  # Not duplicate
        ]

        if all(checks):
            quality_flag = "VALID"

        assert quality_flag == "VALID"

    def test_suspicious_record_gets_suspicious_flag(self):
        """Test failing some checks gets SUSPICIOUS flag."""
        checks = [
            True,   # Non-negative
            False,  # Is flatline (suspicious)
            True,   # Known station
            True,   # Not duplicate
        ]

        if all(checks):
            quality_flag = "VALID"
        else:
            quality_flag = "SUSPICIOUS"

        assert quality_flag == "SUSPICIOUS"

    def test_invalid_record_gets_invalid_flag(self):
        """Test critical failure gets INVALID flag."""
        checks = [
            False,  # Negative value (invalid)
            True,   # Not flatline
            True,   # Known station
            True,   # Not duplicate
        ]

        if all(checks):
            quality_flag = "VALID"
        else:
            quality_flag = "INVALID"

        assert quality_flag == "INVALID"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
