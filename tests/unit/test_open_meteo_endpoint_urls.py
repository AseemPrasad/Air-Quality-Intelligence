"""Regression tests for Open-Meteo endpoint URL construction."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from aq_engine.connectors.models import ConnectorConfig
from aq_engine.connectors.open_meteo import OpenMeteoConnector


def _weather_response(times):
    response = Mock()
    response.status_code = 200
    response.raise_for_status = Mock()
    response.json.return_value = {
        "hourly": {
            "time": times,
            "temperature_2m": [20.0] * len(times),
            "relative_humidity_2m": [50.0] * len(times),
            "wind_speed_10m": [5.0] * len(times),
            "wind_direction_10m": [180.0] * len(times),
            "pressure_msl": [1013.0] * len(times),
            "precipitation": [0.0] * len(times),
            "cloud_cover": [10.0] * len(times),
        }
    }
    return response


@pytest.fixture
def connector():
    config = ConnectorConfig(
        source_name="open_meteo",
        source_type="weather",
        base_url="https://api.open-meteo.com/v1",
        timeout_seconds=10,
    )
    return OpenMeteoConnector(config, session=Mock())


def test_historical_request_uses_archive_host_and_keeps_version(connector):
    start = datetime(2026, 8, 15, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 15, 2, tzinfo=timezone.utc)
    connector._session.get.return_value = _weather_response(
        ["2026-08-15T00:00", "2026-08-15T01:00"]
    )

    connector._fetch_location_weather("station-1", 22.57, 88.36, start, end)

    url = connector._session.get.call_args.args[0]
    assert url == "https://archive-api.open-meteo.com/v1/archive"


def test_forecast_request_keeps_version_and_forecast_path(connector):
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=3)
    times = [
        (start + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M")
        for offset in range(4)
    ]
    connector._session.get.return_value = _weather_response(times)

    connector._fetch_location_weather("station-1", 22.57, 88.36, start, end)

    url = connector._session.get.call_args.args[0]
    assert url == "https://api.open-meteo.com/v1/forecast"


def test_custom_base_url_is_not_rewritten(connector):
    connector.config.base_url = "https://weather-proxy.internal/open-meteo/v1/"

    url = connector._endpoint_url(historical=True)

    assert url == "https://weather-proxy.internal/open-meteo/v1/archive"
