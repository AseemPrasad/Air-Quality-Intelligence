"""Unit tests for SensorDriftValidator in aq_engine.quality.drift."""

from datetime import UTC, datetime, timedelta

import pytest
from aq_engine.quality.drift import SensorDriftValidator


class TestSensorDriftValidator:
    """Test drift detection across stations."""

    def test_empty_records(self):
        v = SensorDriftValidator(min_points=5)
        assert v.flag_records([]) == []

    def test_linear_slope_calculation(self):
        assert SensorDriftValidator._linear_slope([]) == 0.0
        assert SensorDriftValidator._linear_slope([10.0]) == 0.0
        # Slope of [0, 1, 2, 3] is 1.0
        assert pytest.approx(SensorDriftValidator._linear_slope([0.0, 1.0, 2.0, 3.0])) == 1.0

    def test_missing_or_invalid_fields_skipped(self):
        v = SensorDriftValidator(min_points=3)
        records = [
            {"station_id": "", "pollutant": "pm25", "value": 10.0},
            {"station_id": "st1", "pollutant": "", "value": 10.0},
            {"station_id": "st1", "pollutant": "pm25", "value": "invalid"},
            {"station_id": "st1", "pollutant": "pm25", "value": float("nan")},
            {"station_id": "st1", "pollutant": "pm25", "value": True},
        ]
        assert v.flag_records(records) == []

    def test_drift_detected_against_neighbor(self):
        v = SensorDriftValidator(
            min_points=4,
            slope_threshold=0.05,
            neighbor_deviation=0.2,
        )
        base = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)

        # Station 1 has strong upward drift: values [10, 20, 30, 40] -> slope ~ 10.0
        st1_records = [
            {
                "station_id": "st1",
                "pollutant": "pm25",
                "value": 10.0 * (i + 1),
                "observed_at": base + timedelta(hours=i),
            }
            for i in range(4)
        ]

        # Station 2 (neighbor) has stable readings: values [10, 10, 10, 10] -> slope = 0.0
        st2_records = [
            {
                "station_id": "st2",
                "pollutant": "pm25",
                "value": 10.0,
                "observed_at": base + timedelta(hours=i),
            }
            for i in range(4)
        ]

        flagged = v.flag_records(st1_records + st2_records)
        assert len(flagged) == 4
        for r in flagged:
            assert r["station_id"] == "st1"
            assert r["quality_flag"] == "DRIFT_DETECTED"
            assert "Sensor drift detected" in r["quality_reason"]

    def test_sensor_drift_validator_flags_station_deviation_from_neighbors(self):
        start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        stable_records = [
            {
                "source": "openaq",
                "station_id": "stn_base",
                "sensor_id": "sensor-stn_base",
                "pollutant": "pm25",
                "value": 42.0,
                "unit": "µg/m³",
                "observed_at": start + timedelta(hours=i),
                "ingested_at": start + timedelta(hours=i, minutes=5),
                "raw_payload_hash": f"hash-stn_base-{(start + timedelta(hours=i)).isoformat()}",
            }
            for i in range(168)
        ]
        drift_records = [
            {
                "source": "openaq",
                "station_id": "stn_drift",
                "sensor_id": "sensor-stn_drift",
                "pollutant": "pm25",
                "value": 42.0 + (i * 0.25),
                "unit": "µg/m³",
                "observed_at": start + timedelta(hours=i),
                "ingested_at": start + timedelta(hours=i, minutes=5),
                "raw_payload_hash": f"hash-stn_drift-{(start + timedelta(hours=i)).isoformat()}",
            }
            for i in range(168)
        ]

        validator = SensorDriftValidator(min_points=48, slope_threshold=0.05, neighbor_deviation=0.2)
        flagged = validator.flag_records(stable_records + drift_records)

        assert flagged
        assert any(record.get("station_id") == "stn_drift" for record in flagged)
        assert any(record.get("quality_flag") == "DRIFT_DETECTED" for record in flagged)
