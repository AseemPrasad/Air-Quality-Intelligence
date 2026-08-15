"""Tests for forecast and event endpoints."""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from aq_engine.api.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestForecastEndpoint:
    """Test GET /locations/{id}/forecast endpoint."""

    def test_forecast_returns_200(self, client):
        """Test forecast endpoint returns 200."""
        response = client.get("/api/locations/kolkata_001/forecast")

        assert response.status_code == 200

    def test_forecast_response_structure(self, client):
        """Test forecast response structure."""
        response = client.get("/api/locations/kolkata_001/forecast")
        data = response.json()

        assert "location_id" in data
        assert "generated_at" in data
        assert "forecasts" in data
        assert isinstance(data["forecasts"], list)

    def test_forecast_default_horizons(self, client):
        """Test default horizons (1h, 3h, 6h)."""
        response = client.get("/api/locations/kolkata_001/forecast")
        data = response.json()

        horizons = [f["horizon_minutes"] for f in data["forecasts"]]
        assert 60 in horizons  # 1h
        assert 180 in horizons  # 3h
        assert 360 in horizons  # 6h

    def test_forecast_point_has_required_fields(self, client):
        """Test each forecast point has required fields."""
        response = client.get("/api/locations/kolkata_001/forecast")
        data = response.json()

        forecast = data["forecasts"][0]
        required_fields = [
            "horizon_minutes",
            "target_time",
            "predicted_pm25",
            "lower_bound",
            "upper_bound",
            "confidence",
        ]

        for field in required_fields:
            assert field in forecast

    def test_forecast_confidence_range(self, client):
        """Test confidence is between 0 and 1."""
        response = client.get("/api/locations/kolkata_001/forecast")
        data = response.json()

        for forecast in data["forecasts"]:
            assert 0.0 <= forecast["confidence"] <= 1.0

    def test_forecast_target_time_correct(self, client):
        """Test target_time is reference_time + horizon."""
        response = client.get("/api/locations/kolkata_001/forecast")
        data = response.json()

        generated = datetime.fromisoformat(data["generated_at"])

        for forecast in data["forecasts"]:
            target = datetime.fromisoformat(forecast["target_time"])
            horizon_delta = timedelta(minutes=forecast["horizon_minutes"])
            expected_target = generated + horizon_delta

            # Allow 1 minute tolerance
            diff = abs((target - expected_target).total_seconds())
            assert diff < 60

    def test_forecast_invalid_location_returns_404(self, client):
        """Test invalid location returns 404."""
        response = client.get("/api/locations/invalid_location/forecast")

        assert response.status_code == 404


class TestEventsEndpoint:
    """Test GET /locations/{id}/events endpoint."""

    def test_events_returns_200(self, client):
        """Test events endpoint returns 200."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        assert response.status_code == 200

    def test_events_response_structure(self, client):
        """Test events response structure."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        assert "location_id" in data
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_event_has_required_fields(self, client):
        """Test each event has required fields."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        if data["events"]:
            event = data["events"][0]
            required_fields = [
                "event_id",
                "pollutant",
                "start_time",
                "end_time",
                "duration_hours",
                "peak_value",
                "mean_value",
                "peak_anomaly_score",
                "severity",
            ]

            for field in required_fields:
                assert field in event

    def test_event_includes_weather(self, client):
        """Test event includes weather context."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        if data["events"]:
            event = data["events"][0]
            if event.get("weather"):
                weather = event["weather"]
                assert "mean_temperature_c" in weather
                assert "mean_humidity_pct" in weather
                assert "mean_wind_speed_kmh" in weather

    def test_events_invalid_date_range_returns_400(self, client):
        """Test invalid date range returns 400."""
        start = datetime(2026, 8, 15, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        assert response.status_code == 400

    def test_events_invalid_location_returns_404(self, client):
        """Test invalid location returns 404."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/invalid_location/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        assert response.status_code == 404

    def test_events_filtered_by_date(self, client):
        """Test events filtered by date range."""
        # Date before any events
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        end = datetime(2026, 8, 13, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        # May return 0 events if date doesn't overlap
        assert isinstance(data["events"], list)


class TestBaselineEndpoint:
    """Test GET /locations/{id}/baseline endpoint."""

    def test_baseline_returns_200(self, client):
        """Test baseline endpoint returns 200."""
        response = client.get("/api/locations/kolkata_001/baseline")

        assert response.status_code == 200

    def test_baseline_response_structure(self, client):
        """Test baseline response structure."""
        response = client.get("/api/locations/kolkata_001/baseline")
        data = response.json()

        required_fields = [
            "location_id",
            "pollutant",
            "month",
            "hour_of_day",
            "observation_count",
            "median",
            "mad",
            "p50",
            "p75",
            "p90",
            "p95",
            "p99",
        ]

        for field in required_fields:
            assert field in data

    def test_baseline_default_hour_and_month(self, client):
        """Test baseline uses current hour and month by default."""
        from datetime import datetime, timezone

        response = client.get("/api/locations/kolkata_001/baseline")
        data = response.json()

        now = datetime.now(timezone.utc)
        assert data["hour_of_day"] == now.hour
        assert data["month"] == now.month

    def test_baseline_custom_hour(self, client):
        """Test baseline with custom hour."""
        response = client.get(
            "/api/locations/kolkata_001/baseline",
            params={"hour": 15},
        )

        data = response.json()
        assert data["hour_of_day"] == 15

    def test_baseline_custom_month(self, client):
        """Test baseline with custom month."""
        response = client.get(
            "/api/locations/kolkata_001/baseline",
            params={"month": 6},
        )

        data = response.json()
        assert data["month"] == 6

    def test_baseline_percentiles_ordered(self, client):
        """Test percentiles are ordered p50 < p75 < p90 < p95 < p99."""
        response = client.get("/api/locations/kolkata_001/baseline")
        data = response.json()

        assert data["p50"] <= data["p75"]
        assert data["p75"] <= data["p90"]
        assert data["p90"] <= data["p95"]
        assert data["p95"] <= data["p99"]

    def test_baseline_invalid_location_returns_404(self, client):
        """Test invalid location returns 404."""
        response = client.get("/api/locations/invalid_location/baseline")

        assert response.status_code == 404

    def test_baseline_invalid_hour_returns_422(self, client):
        """Test invalid hour returns 422."""
        response = client.get(
            "/api/locations/kolkata_001/baseline",
            params={"hour": 25},
        )

        assert response.status_code == 422

    def test_baseline_invalid_month_returns_422(self, client):
        """Test invalid month returns 422."""
        response = client.get(
            "/api/locations/kolkata_001/baseline",
            params={"month": 13},
        )

        assert response.status_code == 422


class TestTimestamps:
    """Test ISO 8601 timestamp formatting."""

    def test_forecast_times_are_iso(self, client):
        """Test forecast times are ISO 8601."""
        response = client.get("/api/locations/kolkata_001/forecast")
        data = response.json()

        generated = datetime.fromisoformat(data["generated_at"])
        assert generated.tzinfo is not None

        for forecast in data["forecasts"]:
            target = datetime.fromisoformat(forecast["target_time"])
            assert target.tzinfo is not None

    def test_event_times_are_iso(self, client):
        """Test event times are ISO 8601."""
        start = datetime(2026, 8, 14, tzinfo=timezone.utc)
        end = datetime(2026, 8, 15, tzinfo=timezone.utc)

        response = client.get(
            "/api/locations/kolkata_001/events",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

        data = response.json()
        for event in data["events"]:
            start_time = datetime.fromisoformat(event["start_time"])
            end_time = datetime.fromisoformat(event["end_time"])
            assert start_time.tzinfo is not None
            assert end_time.tzinfo is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
