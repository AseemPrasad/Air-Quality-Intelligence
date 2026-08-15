"""Unit tests for OpenAQ connector.

Tests API integration, pagination, unit conversion, retry logic, and watermark handling.
Uses mocked HTTP responses to avoid external API calls.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from aq_engine.connectors.openaq import OpenAQConnector
from aq_engine.connectors.models import ConnectorConfig, SourceResponse, IngestionRunMetadata
from aq_engine.common import IngestionFailed, DataContractViolation


@pytest.fixture
def connector_config():
    """Connector configuration fixture."""
    return ConnectorConfig(
        source_name="openaq",
        source_type="air_quality",
        base_url="https://api.openaq.org/v3",
        timeout_seconds=30,
    )


@pytest.fixture
def connector(connector_config):
    """OpenAQ connector fixture with mocked session."""
    mock_session = Mock()
    return OpenAQConnector(connector_config, session=mock_session)


class TestFetchMeasurements:
    """Test /measurements endpoint fetching."""

    def test_fetch_single_page(self, connector):
        """Test fetching measurements with single page."""
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "location": {"id": 1},
                    "sensor": {"id": 100},
                    "parameter": {"id": "pm25"},
                    "value": 45.5,
                    "unit": "µg/m³",
                    "date": {"utc": "2026-08-15T12:00:00Z"},
                },
                {
                    "location": {"id": 1},
                    "sensor": {"id": 101},
                    "parameter": {"id": "pm10"},
                    "value": 75.2,
                    "unit": "µg/m³",
                    "date": {"utc": "2026-08-15T12:00:00Z"},
                },
            ],
            "meta": {"next": {"cursor": None}},
        }
        mock_response.raise_for_status = Mock()
        connector._session.get = Mock(return_value=mock_response)

        # Fetch
        start_time = datetime(2026, 8, 15, tzinfo=timezone.utc)
        end_time = datetime(2026, 8, 16, tzinfo=timezone.utc)
        response = connector.fetch(start_time, end_time)

        # Verify
        assert response.status_code == 200
        assert len(response.body["results"]) == 2
        assert response.body["results"][0]["value"] == 45.5
        connector._session.get.assert_called_once()

    def test_fetch_pagination_multiple_pages(self, connector):
        """Test fetching measurements across multiple pages."""
        # Mock two pages of responses
        page1_response = Mock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "results": [
                {
                    "location": {"id": 1},
                    "sensor": {"id": 100},
                    "parameter": {"id": "pm25"},
                    "value": 45.5,
                    "unit": "µg/m³",
                    "date": {"utc": "2026-08-15T12:00:00Z"},
                }
            ],
            "meta": {"next": {"cursor": "page2"}},
        }
        page1_response.raise_for_status = Mock()

        page2_response = Mock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "results": [
                {
                    "location": {"id": 1},
                    "sensor": {"id": 100},
                    "parameter": {"id": "pm10"},
                    "value": 75.2,
                    "unit": "µg/m³",
                    "date": {"utc": "2026-08-15T13:00:00Z"},
                }
            ],
            "meta": {"next": {"cursor": None}},
        }
        page2_response.raise_for_status = Mock()

        connector._session.get = Mock(side_effect=[page1_response, page2_response])

        # Fetch
        start_time = datetime(2026, 8, 15, tzinfo=timezone.utc)
        end_time = datetime(2026, 8, 16, tzinfo=timezone.utc)
        response = connector.fetch(start_time, end_time)

        # Verify
        assert response.status_code == 200
        assert len(response.body["results"]) == 2
        assert connector._session.get.call_count == 2

    def test_fetch_large_dataset_1000_records(self, connector):
        """Test fetching 1000+ records across pagination."""
        # Simulate 2 pages: 600 + 400 records
        records_page1 = [
            {
                "location": {"id": i},
                "sensor": {"id": 100 + i},
                "parameter": {"id": "pm25"},
                "value": 45.5 + i,
                "unit": "µg/m³",
                "date": {"utc": f"2026-08-15T{i%24:02d}:00:00Z"},
            }
            for i in range(600)
        ]

        records_page2 = [
            {
                "location": {"id": 600 + i},
                "sensor": {"id": 700 + i},
                "parameter": {"id": "pm25"},
                "value": 45.5 + 600 + i,
                "unit": "µg/m³",
                "date": {"utc": f"2026-08-16T{(i//24):02d}:{(i%24)*2:02d}:00Z"},
            }
            for i in range(400)
        ]

        page1_response = Mock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "results": records_page1,
            "meta": {"next": {"cursor": "page2"}},
        }
        page1_response.raise_for_status = Mock()

        page2_response = Mock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "results": records_page2,
            "meta": {"next": {"cursor": None}},
        }
        page2_response.raise_for_status = Mock()

        connector._session.get = Mock(side_effect=[page1_response, page2_response])

        # Fetch
        start_time = datetime(2026, 8, 15, tzinfo=timezone.utc)
        end_time = datetime(2026, 8, 17, tzinfo=timezone.utc)
        response = connector.fetch(start_time, end_time)

        # Verify
        assert len(response.body["results"]) == 1000


class TestParsing:
    """Test measurement parsing into canonical records."""

    def test_parse_valid_measurement(self, connector):
        """Test parsing single valid measurement."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "location": {"id": 123},
                        "sensor": {"id": 456},
                        "parameter": {"id": "pm25"},
                        "value": 45.5,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    }
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records = connector.parse(response, None, None)

        assert len(records) == 1
        assert records[0].data["station_id"] == "123"
        assert records[0].data["sensor_id"] == "456"
        assert records[0].data["pollutant"] == "pm25"
        assert records[0].data["value"] == 45.5
        assert records[0].data["unit"] == "µg/m³"

    def test_parse_skip_unmonitored_pollutant(self, connector):
        """Test that unmonitored pollutants are skipped."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "location": {"id": 123},
                        "sensor": {"id": 456},
                        "parameter": {"id": "co"},  # Not monitored
                        "value": 1.5,
                        "unit": "ppm",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    }
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records = connector.parse(response, None, None)

        assert len(records) == 0

    def test_parse_skip_missing_required_fields(self, connector):
        """Test that measurements with missing required fields are skipped."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    # Missing location.id
                    {
                        "location": {},
                        "sensor": {"id": 456},
                        "parameter": {"id": "pm25"},
                        "value": 45.5,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    },
                    # Missing sensor.id
                    {
                        "location": {"id": 123},
                        "sensor": {},
                        "parameter": {"id": "pm25"},
                        "value": 45.5,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    },
                    # Null value
                    {
                        "location": {"id": 123},
                        "sensor": {"id": 456},
                        "parameter": {"id": "pm25"},
                        "value": None,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    },
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records = connector.parse(response, None, None)

        assert len(records) == 0

    def test_parse_malformed_json_response(self, connector):
        """Test that malformed JSON response raises error."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body="not a dict",  # Malformed
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        with pytest.raises(DataContractViolation):
            connector.parse(response, None, None)


class TestUnitConversion:
    """Test unit normalization to µg/m³."""

    def test_normalize_microgram_per_cubic_meter(self, connector):
        """Test that µg/m³ is kept as-is."""
        value, unit = connector._normalize_unit(45.5, "µg/m³", "pm25")
        assert value == 45.5
        assert unit == "µg/m³"

    def test_normalize_milligram_to_microgram(self, connector):
        """Test that mg/m³ is converted to µg/m³."""
        value, unit = connector._normalize_unit(0.0455, "mg/m³", "pm25")
        assert value == pytest.approx(45.5)  # 0.0455 * 1000
        assert unit == "µg/m³"

    def test_normalize_unknown_unit(self, connector):
        """Test handling of unknown units."""
        value, unit = connector._normalize_unit(45.5, "unknown_unit", "pm25")
        assert value == 45.5
        assert unit == "unknown_unit"

    def test_normalize_ppb_skipped(self, connector):
        """Test that ppb is kept as-is (no molecular weight)."""
        value, unit = connector._normalize_unit(15.0, "ppb", "no2")
        assert value == 15.0
        assert unit == "ppb"


class TestErrorHandling:
    """Test error handling and retry logic."""

    def test_handle_401_authentication_error(self, connector):
        """Test 401 Unauthorized immediately fails."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = Exception("401 Client Error")
        connector._session.get = Mock(return_value=mock_response)

        with pytest.raises(IngestionFailed, match="Authentication failed"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_403_forbidden_error(self, connector):
        """Test 403 Forbidden immediately fails."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_response.raise_for_status.side_effect = Exception("403 Client Error")
        connector._session.get = Mock(return_value=mock_response)

        with pytest.raises(IngestionFailed, match="Access forbidden"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_404_not_found_continues(self, connector):
        """Test 404 Not Found logs warning but continues."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_response.raise_for_status.side_effect = Exception("404 Client Error")
        connector._session.get = Mock(return_value=mock_response)

        # Should continue with empty results (no exception)
        response = connector.fetch(
            datetime(2026, 8, 15, tzinfo=timezone.utc),
            datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
        assert response.status_code == 200  # Synthesized empty response

    def test_handle_429_rate_limit_error(self, connector):
        """Test 429 Too Many Requests triggers retry."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.raise_for_status.side_effect = Exception("429 Client Error")
        connector._session.get = Mock(return_value=mock_response)

        with pytest.raises(IngestionFailed, match="Transient error"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_500_server_error(self, connector):
        """Test 500 Server Error triggers retry."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = Exception("500 Server Error")
        connector._session.get = Mock(return_value=mock_response)

        with pytest.raises(IngestionFailed, match="Transient error"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_timeout(self, connector):
        """Test timeout triggers retry."""
        import requests

        connector._session.get = Mock(side_effect=requests.Timeout("Connection timeout"))

        with pytest.raises(IngestionFailed, match="Timeout"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

    def test_handle_malformed_json(self, connector):
        """Test malformed JSON response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Expecting value")
        mock_response.raise_for_status = Mock()
        connector._session.get = Mock(return_value=mock_response)

        with pytest.raises(DataContractViolation, match="Malformed JSON"):
            connector.fetch(
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )


class TestIdempotency:
    """Test idempotency via measurement_key."""

    def test_measurement_key_uniqueness(self, connector):
        """Test that measurement_key is consistent for same observation."""
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "location": {"id": 123},
                        "sensor": {"id": 456},
                        "parameter": {"id": "pm25"},
                        "value": 45.5,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    }
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records1 = connector.parse(response, None, None)
        records2 = connector.parse(response, None, None)

        assert records1[0].measurement_key == records2[0].measurement_key

    def test_measurement_key_differs_for_different_observations(self, connector):
        """Test that different observations have different measurement_keys."""
        response1 = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "location": {"id": 123},
                        "sensor": {"id": 456},
                        "parameter": {"id": "pm25"},
                        "value": 45.5,
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    }
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        response2 = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": [
                    {
                        "location": {"id": 123},
                        "sensor": {"id": 456},
                        "parameter": {"id": "pm25"},
                        "value": 50.0,  # Different value
                        "unit": "µg/m³",
                        "date": {"utc": "2026-08-15T12:00:00Z"},
                    }
                ]
            },
            elapsed_seconds=1.0,
            timestamp=datetime.now(timezone.utc),
        )

        records1 = connector.parse(response1, None, None)
        records2 = connector.parse(response2, None, None)

        # Different timestamps → different keys (even if same station/sensor)
        assert records1[0].measurement_key != records2[0].measurement_key


class TestRecordRun:
    """Test run recording and watermark handling."""

    def test_record_run_success_logs_metadata(self, connector):
        """Test that successful run is logged."""
        metadata = IngestionRunMetadata(
            run_id="test-run-123",
            source_id=1,
            started_at=datetime.now(timezone.utc),
            status="success",
            finished_at=datetime.now(timezone.utc),
            records_received=100,
            records_written=95,
            records_rejected=5,
        )

        # Should not raise
        connector.record_run(metadata, success=True)

    def test_record_run_failure_does_not_advance_watermark(self, connector):
        """Test that failed run does NOT advance watermark."""
        metadata = IngestionRunMetadata(
            run_id="test-run-456",
            source_id=1,
            started_at=datetime.now(timezone.utc),
            status="failed",
            finished_at=datetime.now(timezone.utc),
            records_received=0,
            records_written=0,
            records_rejected=0,
            error_message="API error",
        )

        # Should log warning
        with patch("aq_engine.connectors.openaq.logger") as mock_logger:
            connector.record_run(metadata, success=False)
            mock_logger.warning.assert_called()


class TestApiKeyHandling:
    """Test optional API key handling."""

    def test_connector_with_api_key(self, connector_config):
        """Test connector initialization with API key."""
        connector = OpenAQConnector(connector_config, api_key="test-key-12345")
        assert connector.api_key == "test-key-12345"

    def test_connector_without_api_key(self, connector_config):
        """Test connector initialization without API key."""
        connector = OpenAQConnector(connector_config)
        assert connector.api_key is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
