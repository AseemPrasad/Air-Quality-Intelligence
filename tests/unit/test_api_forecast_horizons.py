"""Regression tests for forecast horizon validation."""

from fastapi.testclient import TestClient

from aq_engine.api.main import app


def test_unknown_horizon_returns_400():
    client = TestClient(app)

    response = client.get(
        "/api/locations/kolkata_001/forecast", params={"horizon": "bogus"}
    )

    assert response.status_code == 400
    assert "Unsupported horizon" in response.json()["detail"]


def test_mixed_valid_and_invalid_horizons_return_400():
    client = TestClient(app)

    response = client.get(
        "/api/locations/kolkata_001/forecast", params={"horizon": "1h,24h"}
    )

    assert response.status_code == 400


def test_duplicate_horizons_are_returned_once():
    client = TestClient(app)

    response = client.get(
        "/api/locations/kolkata_001/forecast", params={"horizon": "1h,1h,3h"}
    )

    assert response.status_code == 200
    horizons = [point["horizon_minutes"] for point in response.json()["forecasts"]]
    assert horizons == [60, 180]


def test_empty_horizon_returns_400():
    client = TestClient(app)

    response = client.get(
        "/api/locations/kolkata_001/forecast", params={"horizon": " , "}
    )

    assert response.status_code == 400
