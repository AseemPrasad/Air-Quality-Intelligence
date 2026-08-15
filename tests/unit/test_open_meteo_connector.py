"""Unit tests for Open-Meteo connector.

Tests weather data fetching, location mapping, validation, and hourly alignment.
Uses mocked HTTP responses to avoid external API calls.
"""

import pytest
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

from aq_engine.connectors.open_meteo import OpenMeteoConnector, haversine_distance
from aq_engine.connectors.models import ConnectorConfig, SourceResponse, IngestionRunMetadata
from aq_engine.common import IngestionFailed, DataContractViolation


@pytest.fixture
def connector_config():
    """Connector configuration fixture."""
    return ConnectorConfig(
        source_name="open_meteo",
        source_type="weather",
        base_url="https://api.open-meteo.com/v1",
        timeout_seconds=30,
    )


@pytest.fixture
def connector(connector_config):
    """Open-Meteo connector fixture with mocked session."""
    mock_session = Mock()
    return OpenMeteoConnector(connector_config, session=mock_session)


@pytest.fixture
def connector_with_locations(connector):
    """Connector with pre-configured locations."""
    # Add Kolkata center location
    connector.add_location_mapping("kolkata_center", 22.5726, 88.3639)
    # Add a second location (South Kolkata)
    connector.add_location_mapping("south_kolkata", 22.45, 88.3639)
    return connector


class TestLocationMapping:
    """Test location registration and mapping."""

    def test_add_single_location(self, connector):
        """Test adding a single location."""
        connector.add_location_mapping("station_123", 22.5726, 88.3639)
        assert "station_123" in connector._location_mapping
        assert connector._location_mapping["station_123"] == (22.5726, 88.3639)

    def test_add_multiple_locations(self, connector):
        """Test adding multiple locations."""
        connector.add_location_mapping("station_1", 22.5726, 88.3639)
        connector.add_location_mapping("station_2", 22.45, 88.2)
        assert len(connector._location_mapping) == 2
        assert "station_1" in connector._location_mapping
        assert "station_2" in connector._location_mapping

    def test_add_location_invalid_latitude(self, connector):
        """Test that invalid latitude raises error."""
        with pytest.raises(ValueError, match="Invalid latitude"):
            connector.add_location_mapping("station_bad", 91.0, 88.3639)

    def test_add_location_invalid_longitude(self, connector):
        """Test that invalid longitude raises error."""
        with pytest.raises(ValueError, match="Invalid longitude"):
            connector.add_location_mapping("station_bad", 22.5726, 181.0)

    def test_clear_location_mappings(self, connector_with_locations):
        """Test clearing all location mappings."""
        assert len(connector_with_locations._location_mapping) == 2
        connector_with_locations.clear_location_mappings()
        assert len(connector_with_locations._location_mapping) == 0

    def test_fetch_without_locations_raises_error(self, connector):
        """Test that fetch fails if no locations registered."""
        with pytest.raises(IngestionFailed, match="No locations registered"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )


class TestHaversineDistance:
    """Test haversine distance calculation."""

    def test_haversine_same_point(self):
        """Test distance between same point is zero."""
        distance = haversine_distance(22.5726, 88.3639, 22.5726, 88.3639)
        assert distance == pytest.approx(0.0, abs=0.01)

    def test_haversine_kolkata_to_north(self):
        """Test distance from Kolkata center to a point north."""
        # Roughly 1 degree north ≈ 111 km
        distance = haversine_distance(22.5726, 88.3639, 23.5726, 88.3639)
        assert distance == pytest.approx(111.0, rel=0.05)

    def test_haversine_kolkata_to_east(self):
        """Test distance from Kolkata center to a point east."""
        # At this latitude, 1 degree east ≈ 92 km
        distance = haversine_distance(22.5726, 88.3639, 22.5726, 89.3639)
        assert distance == pytest.approx(92.0, rel=0.05)

    def test_haversine_symmetry(self):
        """Test that distance is symmetric."""
        d1 = haversine_distance(22.5726, 88.3639, 23.0, 89.0)
        d2 = haversine_distance(23.0, 89.0, 22.5726, 88.3639)
        assert d1 == pytest.approx(d2, rel=0.001)


class TestFetchWeather:
    """Test weather data fetching."""

    def test_fetch_single_location_historical(self, connector_with_locations):
        """Test fetching historical weather for single location."""
        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hourly": {
                "time": ["2026-08-15T00:00", "2026-08-15T01:00"],
                "temperature_2m": [28.5, 29.0],
                "relative_humidity_2m": [65, 63],
                "wind_speed_10m": [8.5, 9.0],
                "wind_direction_10m": [180, 185],
                "pressure_msl": [1013.0, 1013.1],
                "precipitation": [0.0, 0.1],
                "cloud_cover": [40, 35],
            }
        }
        mock_response.raise_for_status = Mock()
        connector_with_locations._session.get = Mock(return_value=mock_response)

        # Fetch
        start_time = datetime(2026, 8, 15, tzinfo=timezone.utc)
        end_time = datetime(2026, 8, 16, tzinfo=timezone.utc)
        response = connector_with_locations.fetch(start_time, end_time)

        # Verify
        assert response.status_code == 200
        assert response.body["meta"]["total"] == 4  # 2 locations × 2 hours each
        assert response.body["meta"]["locations"] == 2

    def test_fetch_multiple_locations_aggregates(self, connector_with_locations):
        """Test that weather from multiple locations is aggregated."""
        # Mock API response (same for both locations for simplicity)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hourly": {
                "time": ["2026-08-15T00:00"],
                "temperature_2m": [28.5],
                "relative_humidity_2m": [65],
                "wind_speed_10m": [8.5],
                "wind_direction_10m": [180],
                "pressure_msl": [1013.0],
                "precipitation": [0.0],
                "cloud_cover": [40],
            }
        }
        mock_response.raise_for_status = Mock()
        connector_with_locations._session.get = Mock(return_value=mock_response)

        # Fetch
        response = connector_with_locations.fetch(
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            datetime(2026, 8, 16, tzinfo=timezone.utc),
        )

        # Verify: 2 locations × 1 hour each = 2 records
        assert response.body["meta"]["total"] == 2
        assert response.body["meta"]["locations"] == 2

    def test_fetch_partial_failure_continues(self, connector_with_locations):
        """Test that failure to fetch one location doesn't stop others."""
        # First location fails, second succeeds
        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "hourly": {
                "time": ["2026-08-15T00:00"],
                "temperature_2m": [28.5],
                "relative_humidity_2m": [65],
                "wind_speed_10m": [8.5],
                "wind_direction_10m": [180],
                "pressure_msl": [1013.0],
                "precipitation": [0.0],
                "cloud_cover": [40],
            }
        }
        success_response.raise_for_status = Mock()

        fail_response = Mock()
        fail_response.status_code = 404
        fail_response.raise_for_status.side_effect = Exception("404 Not Found")

        connector_with_locations._session.get = Mock(side_effect=[fail_response, success_response])

        # Fetch should continue despite first location failure
        response = connector_with_locations.fetch(
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            datetime(2026, 8, 16, tzinfo=timezone.utc),
        )

        # Should have data from second location only
        assert response.body["meta"]["total"] == 1


class TestParsing:
    """Test weather record parsing."""

    def test_parse_valid_weather_record(self, connector):
        """Test parsing single valid weather record."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "source": "open_meteo",
                        "location_id": "123",
                        "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                        "temperature_c": 28.5,
                        "humidity_pct": 65,
                        "wind_speed_kmh": 8.5,
                        "wind_direction_deg": 180,
                        "pressure_hpa": 1013.0,
                        "precipitation_mm": 0.1,
                        "cloud_cover_pct": 40,
                        "ingested_at": datetime.now(timezone.utc),
                        "raw_payload_hash": "abc123",
                    }
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records = connector.parse(response, None, None)

        assert len(records) == 1
        assert records[0].data["temperature_c"] == 28.5
        assert records[0].data["humidity_pct"] == 65

    def test_parse_multiple_records(self, connector):
        """Test parsing multiple weather records."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "source": "open_meteo",
                        "location_id": "123",
                        "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                        "temperature_c": 28.5,
                        "humidity_pct": 65,
                        "wind_speed_kmh": 8.5,
                        "wind_direction_deg": 180,
                        "pressure_hpa": 1013.0,
                        "precipitation_mm": 0.1,
                        "cloud_cover_pct": 40,
                        "ingested_at": datetime.now(timezone.utc),
                        "raw_payload_hash": "abc123",
                    },
                    {
                        "source": "open_meteo",
                        "location_id": "124",
                        "observed_at": datetime(2026, 8, 15, 13, 0, 0, tzinfo=timezone.utc),
                        "temperature_c": 29.0,
                        "humidity_pct": 62,
                        "wind_speed_kmh": 9.0,
                        "wind_direction_deg": 185,
                        "pressure_hpa": 1013.1,
                        "precipitation_mm": 0.0,
                        "cloud_cover_pct": 35,
                        "ingested_at": datetime.now(timezone.utc),
                        "raw_payload_hash": "abc123",
                    },
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records = connector.parse(response, None, None)

        assert len(records) == 2

    def test_parse_malformed_response(self, connector):
        """Test that malformed response raises error."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body="not a dict",
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        with pytest.raises(DataContractViolation):
            connector.parse(response, None, None)


class TestValidation:
    """Test weather parameter validation."""

    def test_validate_temperature_in_range(self, connector):
        """Test temperature within acceptable range."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is not None

    def test_validate_temperature_below_minimum(self, connector):
        """Test temperature below acceptable range."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=-100.0,  # Below -60°C
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is None

    def test_validate_temperature_above_maximum(self, connector):
        """Test temperature above acceptable range."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=100.0,  # Above 60°C
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is None

    def test_validate_humidity_in_range(self, connector):
        """Test humidity within valid range."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is not None

    def test_validate_humidity_above_100(self, connector):
        """Test humidity above 100% is invalid."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=105.0,  # Above 100%
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is None

    def test_validate_wind_direction_in_range(self, connector):
        """Test wind direction within valid range."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=359.9,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is not None

    def test_validate_wind_direction_above_360(self, connector):
        """Test wind direction above 360° is invalid."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=361.0,  # Above 360°
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is None

    def test_validate_pressure_in_range(self, connector):
        """Test pressure within valid range."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is not None

    def test_validate_null_optional_fields_allowed(self, connector):
        """Test that null optional fields are allowed."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=65.0,
            wind_speed=None,  # Optional
            wind_direction=None,  # Optional
            pressure=None,  # Optional
            precipitation=None,  # Optional
            cloud_cover=None,  # Optional
            raw_payload_hash="abc123",
        )
        assert record is not None
        assert record["wind_speed_kmh"] is None
        assert record["wind_direction_deg"] is None

    def test_validate_missing_required_temperature(self, connector):
        """Test that missing temperature is invalid."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=None,  # Required
            humidity=65.0,
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is None

    def test_validate_missing_required_humidity(self, connector):
        """Test that missing humidity is invalid."""
        record = connector._build_weather_record(
            station_id="123",
            latitude=22.5726,
            longitude=88.3639,
            observed_at=datetime.now(timezone.utc),
            temperature=28.5,
            humidity=None,  # Required
            wind_speed=8.5,
            wind_direction=180.0,
            pressure=1013.0,
            precipitation=0.1,
            cloud_cover=40.0,
            raw_payload_hash="abc123",
        )
        assert record is None


class TestErrorHandling:
    """Test error handling for API failures."""

    def test_handle_404_not_found(self, connector_with_locations):
        """Test 404 Not Found for invalid coordinates."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.raise_for_status.side_effect = Exception("404 Client Error")
        connector_with_locations._session.get = Mock(return_value=mock_response)

        with pytest.raises(IngestionFailed, match="Location not found"):
            connector_with_locations.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_500_server_error(self, connector_with_locations):
        """Test 500 Server Error triggers retry."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = Exception("500 Server Error")
        connector_with_locations._session.get = Mock(return_value=mock_response)

        with pytest.raises(IngestionFailed, match="Transient error"):
            connector_with_locations.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_timeout(self, connector_with_locations):
        """Test timeout triggers retry."""
        import requests

        connector_with_locations._session.get = Mock(side_effect=requests.Timeout("Connection timeout"))

        with pytest.raises(IngestionFailed, match="Timeout"):
            connector_with_locations.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_malformed_json(self, connector_with_locations):
        """Test malformed JSON response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Expecting value")
        mock_response.raise_for_status = Mock()
        connector_with_locations._session.get = Mock(return_value=mock_response)

        with pytest.raises(DataContractViolation, match="Malformed JSON"):
            connector_with_locations.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )


class TestRecordRun:
    """Test run recording and watermark handling."""

    def test_record_run_success(self, connector):
        """Test that successful run is logged."""
        metadata = IngestionRunMetadata(
            run_id="test-run-123",
            source_id=2,
            started_at=datetime.now(timezone.utc),
            status="success",
            finished_at=datetime.now(timezone.utc),
            records_received=100,
            records_written=100,
            records_rejected=0,
        )

        # Should not raise
        connector.record_run(metadata, success=True)

    def test_record_run_failure(self, connector):
        """Test that failed run is logged without watermark advancement."""
        metadata = IngestionRunMetadata(
            run_id="test-run-456",
            source_id=2,
            started_at=datetime.now(timezone.utc),
            status="failed",
            finished_at=datetime.now(timezone.utc),
            records_received=0,
            records_written=0,
            records_rejected=0,
            error_message="API error",
        )

        # Should log warning
        with patch("aq_engine.connectors.open_meteo.logger") as mock_logger:
            connector.record_run(metadata, success=False)
            mock_logger.warning.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
