"""Unit tests for FlatlineValidator in aq_engine.quality.flatline."""

from datetime import UTC, datetime, timedelta

from aq_engine.quality.flatline import FlatlineValidator


class TestFlatlineValidator:
    """Test flatline detection logic."""

    def test_empty_records(self):
        validator = FlatlineValidator(min_hours=6)
        assert validator.flag_records([]) == []

    def test_missing_fields_skipped(self):
        validator = FlatlineValidator(min_hours=3)
        records = [
            {"station_id": "", "pollutant": "pm25", "value": 10.0},
            {"station_id": "st1", "pollutant": "", "value": 10.0},
            {"value": 10.0},
        ]
        assert validator.flag_records(records) == []

    def test_varying_values_not_flagged(self):
        validator = FlatlineValidator(min_hours=3)
        base = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
        records = [
            {
                "station_id": "st1",
                "pollutant": "pm25",
                "value": 10.0 + i,
                "observed_at": base + timedelta(hours=i),
            }
            for i in range(5)
        ]
        assert validator.flag_records(records) == []

    def test_constant_run_flagged(self):
        validator = FlatlineValidator(min_hours=3)
        base = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
        records = [
            {
                "station_id": "st1",
                "pollutant": "pm25",
                "value": 42.0,
                "observed_at": base + timedelta(hours=i),
            }
            for i in range(4)
        ]
        flagged = validator.flag_records(records)
        assert len(flagged) >= 3
        for r in flagged:
            assert r["quality_flag"] == "STUCK_SENSOR"
            assert "Flatline detected" in r["quality_reason"]

    def test_non_numeric_or_none_resets_run(self):
        validator = FlatlineValidator(min_hours=3)
        base = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
        records = [
            {"station_id": "st1", "pollutant": "pm25", "value": 42.0, "observed_at": base},
            {"station_id": "st1", "pollutant": "pm25", "value": None, "observed_at": base + timedelta(hours=1)},
            {"station_id": "st1", "pollutant": "pm25", "value": 42.0, "observed_at": base + timedelta(hours=2)},
            {"station_id": "st1", "pollutant": "pm25", "value": 42.0, "observed_at": base + timedelta(hours=3)},
        ]
        # Only 2 consecutive after reset -> threshold 3 not reached
        flagged = validator.flag_records(records)
        assert len(flagged) == 0

    def test_flatline_validator_flags_six_hour_constant_signal(self):
        start = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
        records = [
            {
                "source": "openaq",
                "station_id": "stn_flat",
                "sensor_id": "sensor-stn_flat",
                "pollutant": "pm25",
                "value": 42.0,
                "unit": "µg/m³",
                "observed_at": start + timedelta(hours=i),
                "ingested_at": start + timedelta(hours=i, minutes=5),
                "raw_payload_hash": f"hash-stn_flat-{(start + timedelta(hours=i)).isoformat()}",
            }
            for i in range(6)
        ]

        validator = FlatlineValidator(min_hours=6)
        flagged = validator.flag_records(records)

        assert flagged
        assert all(record.get("quality_flag") == "STUCK_SENSOR" for record in flagged)
