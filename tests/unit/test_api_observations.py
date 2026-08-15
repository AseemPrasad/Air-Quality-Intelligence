"""Tests for observations and locations endpoints."""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from aq_engine.api.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestLocationsEndpoint:
    """Test GET /locations endpoint."""

    def test_get_locations_returns_200(self, client):
        """Test locations endpoint returns 200."""
        response = client.get("/api/locations")

        assert response.status_code == 200

    def test_get_locations_returns_list(self, client):
        """Test locations endpoint returns list."""
        response = client.get("/api/locations")
        data = response.json()

        assert "locations" in data
        assert isinstance(data["locations"], list)
        assert len(data["locations"]) > 0

    def test_location_has_required_fields(self, client):
        """Test each location has required metadata."""
        response = client.get("/api/locations")
        data = response.json()

        location = data["locations"][0]
        required_fields = [
            "location_id",
            "name",
            "city",
            "country",
            "latitude",
            "longitude",
            "timezone",
            "active_stations",
            "last_update",
        ]

        for field in required_fields:
            assert field in location

    def test_location_coordinates_are_floats(self, client):
        """Test latitude/longitude are numeric."""
        response = client.get("/api/locations")
        data = response.json()

        location = data["locations"][0]
        assert isinstance(location["latitude"], float)
        assert isinstance(location["longitude"], float)


class TestCurrentObservationEndpoint:
    """Test GET /locations/{id}/current endpoint."""

    def test_current_observation_returns_200(self, client):
        """Test current observation endpoint returns 200."""
        response = client.get("/api/locations/kolkata_001/current")

        assert response.status_code == 200

    def test_current_observation_structure(self, client):
        """Test current observation response structure."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        required_fields = [
            "location_id",
            "current_time",
            "pollutants",
            "weather",
            "freshness",
        ]

        for field in required_fields:
            assert field in data

    def test_current_observation_has_pollutants(self, client):
        """Test current observation includes pollutants."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        assert isinstance(data["pollutants"], list)
        assert len(data["pollutants"]) > 0

    def test_pollutant_has_required_fields(self, client):
        """Test each pollutant has required fields."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        pollutant = data["pollutants"][0]
        required_fields = [
            "pollutant",
            "value",
            "unit",
            "timestamp",
            "quality_flag",
        ]

        for field in required_fields:
            assert field in pollutant

    def test_pollutant_includes_anomaly_info(self, client):
        """Test pollutant includes anomaly severity."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        pollutant = data["pollutants"][0]
        assert "anomaly_severity" in pollutant
        assert "anomaly_score" in pollutant

    def test_weather_has_units(self, client):
        """Test weather fields include unit suffixes."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        weather = data["weather"]
        # Unit suffixes in field names
        assert "temperature_c" in weather  # Celsius
        assert "humidity_pct" in weather  # Percentage
        assert "wind_speed_kmh" in weather  # km/h

    def test_freshness_status(self, client):
        """Test freshness includes status."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        freshness = data["freshness"]
        assert "data_age_minutes" in freshness
        assert "expected_interval_minutes" in freshness
        assert "status" in freshness
        assert freshness["status"] in ["fresh", "stale", "missing"]

    def test_invalid_location_returns_404(self, client):
        """Test invalid location returns 404."""
        response = client.get("/api/locations/invalid_location/current")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestHistoryEndpoint:
    """Test GET /locations/{id}/history endpoint."""

    def test_history_with_valid_params_returns_200(self, client):
        """Test history endpoint with valid parameters."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        assert response.status_code == 200

    def test_history_returns_data_points(self, client):
        """Test history returns time series data."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 3, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

    def test_history_data_point_has_required_fields(self, client):
        """Test each data point has required fields."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 1, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        point = data["data"][0]

        required_fields = [
            "mean_value",
            "median_value",
            "min_value",
            "max_value",
            "observation_count",
            "coverage_pct",
        ]

        for field in required_fields:
            assert field in point

    def test_history_hourly_grain(self, client):
        """Test hourly grain returns hour_start."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 2, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "grain": "hourly",
            },
        )

        data = response.json()
        assert data["grain"] == "hourly"
        point = data["data"][0]
        assert "hour_start" in point

    def test_history_daily_grain(self, client):
        """Test daily grain returns day_start."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 16, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "grain": "daily",
            },
        )

        data = response.json()
        assert data["grain"] == "daily"
        point = data["data"][0]
        assert "day_start" in point

    def test_history_invalid_date_range_returns_400(self, client):
        """Test invalid date range returns 400."""
        start = datetime(2026, 8, 15, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        assert response.status_code == 400

    def test_history_invalid_location_returns_404(self, client):
        """Test invalid location returns 404."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/invalid_location/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        assert response.status_code == 404

    def test_history_filters_by_pollutant(self, client):
        """Test history includes pollutant parameter."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 1, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "pollutant": "PM10",
            },
        )

        data = response.json()
        assert data["pollutant"] == "PM10"


class TestTimestamps:
    """Test ISO 8601 timestamp formatting."""

    def test_locations_last_update_is_iso(self, client):
        """Test location last_update is ISO 8601."""
        response = client.get("/api/locations")
        location = response.json()["locations"][0]

        # Should be parseable as ISO 8601
        timestamp = datetime.fromisoformat(location["last_update"])
        assert timestamp.tzinfo is not None

    def test_current_observation_times_are_iso(self, client):
        """Test current observation timestamps are ISO 8601."""
        response = client.get("/api/locations/kolkata_001/current")
        data = response.json()

        # All timestamps should be ISO 8601
        current_time = datetime.fromisoformat(data["current_time"])
        assert current_time.tzinfo is not None

        pollutant = data["pollutants"][0]
        obs_time = datetime.fromisoformat(pollutant["timestamp"])
        assert obs_time.tzinfo is not None

    def test_history_times_are_iso(self, client):
        """Test history timestamps are ISO 8601."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 1, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        point = data["data"][0]

        # hour_start should be ISO 8601
        hour = datetime.fromisoformat(point["hour_start"])
        assert hour.tzinfo is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
