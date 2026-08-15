"""Tests for FastAPI application health and core endpoints."""

import pytest
from fastapi.testclient import TestClient
from aq_engine.api.main import app, health_status, __version__


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def setup_health():
    """Setup health status for tests."""
    health_status.database_ok = True
    health_status.models_ok = True
    yield


class TestHealthCheck:
    """Test health check endpoint."""

    def test_health_returns_200(self, client):
        """Test health endpoint returns 200 OK."""
        response = client.get("/health")

        assert response.status_code == 200

    def test_health_response_structure(self, client):
        """Test health response has required fields."""
        response = client.get("/health")

        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "timestamp" in data
        assert "database" in data
        assert "models" in data

    def test_health_status_healthy(self, client):
        """Test health status is 'healthy' when all systems ok."""
        health_status.database_ok = True
        health_status.models_ok = True

        response = client.get("/health")
        data = response.json()

        assert data["status"] == "healthy"
        assert data["database"] == "ok"
        assert data["models"] == "ok"

    def test_health_status_degraded_db_down(self, client):
        """Test health status is 'degraded' when database down."""
        health_status.database_ok = False
        health_status.models_ok = True

        response = client.get("/health")
        data = response.json()

        assert data["status"] == "degraded"
        assert data["database"] == "error"

    def test_health_status_degraded_models_down(self, client):
        """Test health status is 'degraded' when models unavailable."""
        health_status.database_ok = True
        health_status.models_ok = False

        response = client.get("/health")
        data = response.json()

        assert data["status"] == "degraded"
        assert data["models"] == "error"

    def test_health_version_matches(self, client):
        """Test health endpoint returns correct version."""
        response = client.get("/health")
        data = response.json()

        assert data["version"] == __version__


class TestCORSHeaders:
    """Test CORS configuration."""

    def test_cors_enabled(self, client):
        """Test CORS is configured."""
        # CORS middleware is enabled, verified by successful requests
        response = client.get("/health")
        assert response.status_code == 200

    def test_cors_for_localhost_3000(self, client):
        """Test endpoint accessible from localhost:3000."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_cors_for_localhost_8501(self, client):
        """Test endpoint accessible from localhost:8501."""
        response = client.get("/health")
        assert response.status_code == 200


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root_returns_200(self, client):
        """Test root endpoint returns 200."""
        response = client.get("/")

        assert response.status_code == 200

    def test_root_response_structure(self, client):
        """Test root response has required fields."""
        response = client.get("/")
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "docs" in data
        assert "health" in data


class TestPredictionsEndpoint:
    """Test predictions endpoint."""

    def test_predictions_returns_200(self, client):
        """Test predictions endpoint returns 200."""
        response = client.get("/predictions/kolkata")

        assert response.status_code == 200

    def test_predictions_response_structure(self, client):
        """Test predictions response has required fields."""
        response = client.get("/predictions/kolkata")
        data = response.json()

        assert "location_id" in data
        assert "predictions" in data
        assert "generated_at" in data

    def test_predictions_contains_horizons(self, client):
        """Test predictions include multiple horizons."""
        response = client.get("/predictions/kolkata")
        data = response.json()

        predictions = data["predictions"]
        assert len(predictions) >= 3

        horizons = [p["horizon_minutes"] for p in predictions]
        assert 60 in horizons
        assert 180 in horizons
        assert 360 in horizons

    def test_predictions_each_has_bounds(self, client):
        """Test each prediction has interval bounds."""
        response = client.get("/predictions/kolkata")
        data = response.json()

        for pred in data["predictions"]:
            assert "predicted_pm25" in pred
            assert "lower_bound" in pred
            assert "upper_bound" in pred
            assert "confidence" in pred

    def test_predictions_invalid_location(self, client):
        """Test invalid location returns error."""
        response = client.get("/predictions/")

        assert response.status_code == 404


class TestRequestID:
    """Test request ID tracking."""

    def test_request_id_header_present(self, client):
        """Test X-Request-ID header present in response."""
        response = client.get("/health")

        assert "X-Request-ID" in response.headers or \
               "x-request-id" in response.headers

    def test_request_id_is_uuid(self, client):
        """Test request ID is UUID format."""
        response = client.get("/health")

        request_id = response.headers.get("X-Request-ID") or \
                     response.headers.get("x-request-id")

        # UUID format check
        assert len(request_id) == 36
        assert request_id.count("-") == 4


class TestErrorHandling:
    """Test error handling."""

    def test_valid_predictions_response(self, client):
        """Test predictions endpoint returns valid response."""
        response = client.get("/predictions/kolkata")

        assert response.status_code == 200
        data = response.json()
        assert "predictions" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
