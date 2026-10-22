"""Regression tests for Open-Meteo datetime window filtering."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from aq_engine.connectors.models import ConnectorConfig
from aq_engine.connectors.open_meteo import OpenMeteoConnector


@pytest.fixture
def connector():
    config = ConnectorConfig(
        source_name="open_meteo",
        source_type="weather",
        base_url="https://api.open-meteo.com/v1",
        timeout_seconds=10,
    )
    connector = OpenMeteoConnector(config, session=Mock())

    response = Mock()
    response.status_code = 200
    response.raise_for_status = Mock()
    response.json.return_value = {
        "hourly": {
            "time": [
                "2026-08-15T00:00",
                "2026-08-15T01:00",
                "2026-08-15T02:00",
                "2026-08-15T03:00",
            ],
            "temperature_2m": [19.0, 20.0, 21.0, 22.0],
            "relative_humidity_2m": [55.0] * 4,
            "wind_speed_10m": [5.0] * 4,
            "wind_direction_10m": [180.0] * 4,
            "pressure_msl": [1013.0] * 4,
            "precipitation": [0.0] * 4,
            "cloud_cover": [10.0] * 4,
        }
    }
    connector._session.get.return_value = response
    return connector


def test_returns_only_records_inside_requested_window(connector):
    start = datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 15, 2, 30, tzinfo=timezone.utc)

    records = connector._fetch_location_weather(
        "station-1", 22.57, 88.36, start, end
    )

    assert [record["observed_at"].hour for record in records] == [1, 2]


def test_includes_records_on_window_boundaries(connector):
    start = datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)

    records = connector._fetch_location_weather(
        "station-1", 22.57, 88.36, start, end
    )

    assert [record["observed_at"].hour for record in records] == [1, 2, 3]
