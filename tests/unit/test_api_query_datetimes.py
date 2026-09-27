"""Date query parameters without a UTC offset must not crash the API."""

import pytest
from fastapi.testclient import TestClient

from aq_engine.api.main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("endpoint", ["events", "history"])
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-08-14T00:00:00", "2026-08-16T00:00:00"),
        ("2026-08-14T00:00:00", "2026-08-16T00:00:00Z"),
        ("2026-08-14T00:00:00Z", "2026-08-16T00:00:00"),
    ],
)
def test_naive_timestamps_are_read_as_utc(client, endpoint, start, end):
    response = client.get(
        f"/api/locations/kolkata_001/{endpoint}",
        params={"start_date": start, "end_date": end},
    )

    assert response.status_code == 200, response.text


def test_naive_range_matches_the_same_range_in_utc(client):
    naive = client.get(
        "/api/locations/kolkata_001/events",
        params={"start_date": "2026-08-14T00:00:00", "end_date": "2026-08-16T00:00:00"},
    )
    utc = client.get(
        "/api/locations/kolkata_001/events",
        params={
            "start_date": "2026-08-14T00:00:00Z",
            "end_date": "2026-08-16T00:00:00Z",
        },
    )

    assert naive.json()["events"] == utc.json()["events"]


def test_inverted_naive_range_is_still_rejected(client):
    response = client.get(
        "/api/locations/kolkata_001/history",
        params={
            "start_date": "2026-08-16T00:00:00",
            "end_date": "2026-08-14T00:00:00Z",
        },
    )

    assert response.status_code == 400
