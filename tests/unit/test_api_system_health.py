"""Tests for system health and data quality endpoints."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from aq_engine.api.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Test GET /system/health endpoint."""

    def test_health_returns_200(self, client):
        """Test health endpoint returns 200."""
        response = client.get("/api/system/health")

        assert response.status_code == 200

    def test_health_response_structure(self, client):
        """Test health response has required fields."""
        response = client.get("/api/system/health")
        data = response.json()

        required_fields = [
            "system_status",
            "timestamp",
            "components",
        ]

        for field in required_fields:
            assert field in data

    def test_health_system_status_valid(self, client):
        """Test system_status is healthy or degraded."""
        response = client.get("/api/system/health")
        data = response.json()

        assert data["system_status"] in ["healthy", "degraded"]

    def test_health_timestamp_is_iso(self, client):
        """Test timestamp is ISO 8601."""
        response = client.get("/api/system/health")
        data = response.json()

        # Should be parseable as ISO 8601
        timestamp = datetime.fromisoformat(data["timestamp"])
        assert timestamp.tzinfo is not None

    def test_health_has_all_components(self, client):
        """Test health response includes all components."""
        response = client.get("/api/system/health")
        data = response.json()

        components = data["components"]
        required_components = [
            "database",
            "ingestion",
            "data_quality",
            "ml_models",
        ]

        for component in required_components:
            assert component in components

    def test_database_component_structure(self, client):
        """Test database component has required fields."""
        response = client.get("/api/system/health")
        data = response.json()

        db = data["components"]["database"]
        required_fields = ["status", "latency_ms", "connected"]

        for field in required_fields:
            assert field in db

    def test_database_component_valid_values(self, client):
        """Test database component has valid values."""
        response = client.get("/api/system/health")
        data = response.json()

        db = data["components"]["database"]
        assert db["status"] in ["ok", "error"]
        assert isinstance(db["latency_ms"], int)
        assert isinstance(db["connected"], bool)

    def test_ingestion_component_structure(self, client):
        """Test ingestion component has required fields."""
        response = client.get("/api/system/health")
        data = response.json()

        ingestion = data["components"]["ingestion"]
        required_fields = [
            "status",
            "last_openaq_run",
            "last_weather_run",
            "openaq_freshness_minutes",
            "weather_freshness_minutes",
        ]

        for field in required_fields:
            assert field in ingestion

    def test_ingestion_component_timestamps(self, client):
        """Test ingestion timestamps are ISO 8601."""
        response = client.get("/api/system/health")
        data = response.json()

        ingestion = data["components"]["ingestion"]

        openaq_ts = datetime.fromisoformat(ingestion["last_openaq_run"])
        assert openaq_ts.tzinfo is not None

        weather_ts = datetime.fromisoformat(ingestion["last_weather_run"])
        assert weather_ts.tzinfo is not None

    def test_quality_component_structure(self, client):
        """Test data quality component has required fields."""
        response = client.get("/api/system/health")
        data = response.json()

        quality = data["components"]["data_quality"]
        required_fields = [
            "status",
            "total_records_last_24h",
            "rejected_records_last_24h",
            "rejection_rate_pct",
            "coverage_pct",
        ]

        for field in required_fields:
            assert field in quality

    def test_quality_component_percentages(self, client):
        """Test data quality metrics are reasonable."""
        response = client.get("/api/system/health")
        data = response.json()

        quality = data["components"]["data_quality"]

        # Rejection rate should be <= 100%
        assert 0 <= quality["rejection_rate_pct"] <= 100

        # Coverage should be <= 100%
        assert 0 <= quality["coverage_pct"] <= 100

    def test_ml_models_component_structure(self, client):
        """Test ML models component has required fields."""
        response = client.get("/api/system/health")
        data = response.json()

        models = data["components"]["ml_models"]
        required_fields = [
            "status",
            "production_model",
            "model_mae",
            "model_age_hours",
        ]

        for field in required_fields:
            assert field in models

    def test_ml_models_component_valid_values(self, client):
        """Test ML models component has valid values."""
        response = client.get("/api/system/health")
        data = response.json()

        models = data["components"]["ml_models"]
        assert models["status"] in ["ok", "error"]
        assert isinstance(models["production_model"], str)
        assert isinstance(models["model_mae"], (int, float))
        assert models["model_age_hours"] >= 0


class TestQualityEndpoint:
    """Test GET /system/quality endpoint."""

    def test_quality_returns_200(self, client):
        """Test quality endpoint returns 200."""
        response = client.get("/api/system/quality")

        assert response.status_code == 200

    def test_quality_response_structure(self, client):
        """Test quality response has required fields."""
        response = client.get("/api/system/quality")
        data = response.json()

        required_fields = [
            "report_time",
            "summary",
            "by_source",
            "by_location",
            "by_station_health",
        ]

        for field in required_fields:
            assert field in data

    def test_quality_report_time_is_iso(self, client):
        """Test report_time is ISO 8601."""
        response = client.get("/api/system/quality")
        data = response.json()

        report_time = datetime.fromisoformat(data["report_time"])
        assert report_time.tzinfo is not None

    def test_quality_summary_structure(self, client):
        """Test summary has all required fields."""
        response = client.get("/api/system/quality")
        data = response.json()

        summary = data["summary"]
        required_fields = [
            "total_records",
            "valid_records",
            "suspicious_records",
            "invalid_records",
            "duplicate_records",
        ]

        for field in required_fields:
            assert field in summary

    def test_quality_summary_values_consistent(self, client):
        """Test summary values are internally consistent."""
        response = client.get("/api/system/quality")
        data = response.json()

        summary = data["summary"]

        # Valid + suspicious + invalid = total
        accounted = (
            summary["valid_records"]
            + summary["suspicious_records"]
            + summary["invalid_records"]
        )
        assert accounted <= summary["total_records"]

    def test_quality_by_source_structure(self, client):
        """Test by_source has required fields."""
        response = client.get("/api/system/quality")
        data = response.json()

        assert isinstance(data["by_source"], list)
        assert len(data["by_source"]) > 0

        for source in data["by_source"]:
            required_fields = ["source", "total", "valid", "suspicious", "invalid"]
            for field in required_fields:
                assert field in source

    def test_quality_by_source_values_consistent(self, client):
        """Test by_source values are consistent."""
        response = client.get("/api/system/quality")
        data = response.json()

        for source in data["by_source"]:
            accounted = source["valid"] + source["suspicious"] + source["invalid"]
            assert accounted <= source["total"]

    def test_quality_by_location_structure(self, client):
        """Test by_location has required fields."""
        response = client.get("/api/system/quality")
        data = response.json()

        assert isinstance(data["by_location"], list)
        assert len(data["by_location"]) > 0

        for location in data["by_location"]:
            required_fields = ["location_id", "total", "valid_pct", "coverage_pct"]
            for field in required_fields:
                assert field in location

    def test_quality_by_location_percentages(self, client):
        """Test by_location percentages are valid."""
        response = client.get("/api/system/quality")
        data = response.json()

        for location in data["by_location"]:
            # Percentages should be 0-100
            assert 0 <= location["valid_pct"] <= 100
            assert 0 <= location["coverage_pct"] <= 100

    def test_quality_by_station_health_structure(self, client):
        """Test by_station_health has required fields."""
        response = client.get("/api/system/quality")
        data = response.json()

        assert isinstance(data["by_station_health"], list)
        assert len(data["by_station_health"]) > 0

        for station in data["by_station_health"]:
            required_fields = ["station_id", "health_score", "status"]
            for field in required_fields:
                assert field in station

    def test_quality_by_station_health_scores(self, client):
        """Test health scores are 0-100."""
        response = client.get("/api/system/quality")
        data = response.json()

        for station in data["by_station_health"]:
            assert 0 <= station["health_score"] <= 100

    def test_quality_by_station_health_status_valid(self, client):
        """Test station status values are valid."""
        response = client.get("/api/system/quality")
        data = response.json()

        valid_statuses = ["healthy", "degraded", "offline"]
        for station in data["by_station_health"]:
            assert station["status"] in valid_statuses

    def test_quality_by_station_health_sorted_by_score(self, client):
        """Test stations are sorted by health score (descending)."""
        response = client.get("/api/system/quality")
        data = response.json()

        stations = data["by_station_health"]
        scores = [s["health_score"] for s in stations]

        # Check if sorted in descending order
        assert scores == sorted(scores, reverse=True)

    def test_quality_station_offline_has_low_score(self, client):
        """Test offline stations have low health score."""
        response = client.get("/api/system/quality")
        data = response.json()

        stations = data["by_station_health"]
        offline_stations = [s for s in stations if s["status"] == "offline"]

        # Offline stations should have health_score < 60
        for station in offline_stations:
            assert station["health_score"] < 60

    def test_quality_healthy_station_has_high_score(self, client):
        """Test healthy stations have high health score."""
        response = client.get("/api/system/quality")
        data = response.json()

        stations = data["by_station_health"]
        healthy_stations = [s for s in stations if s["status"] == "healthy"]

        # Healthy stations should have health_score > 80
        for station in healthy_stations:
            assert station["health_score"] > 80


class TestHealthQualityIntegration:
    """Test integration between health and quality endpoints."""

    def test_both_endpoints_return_valid_timestamps(self, client):
        """Test both endpoints return timestamps in same format."""
        health_response = client.get("/api/system/health")
        quality_response = client.get("/api/system/quality")

        health_time = datetime.fromisoformat(health_response.json()["timestamp"])
        quality_time = datetime.fromisoformat(quality_response.json()["report_time"])

        # Both should be timezone-aware
        assert health_time.tzinfo is not None
        assert quality_time.tzinfo is not None

    def test_health_records_match_quality_records(self, client):
        """Test health and quality endpoint records are related."""
        health_response = client.get("/api/system/health")
        quality_response = client.get("/api/system/quality")

        health_data = health_response.json()
        quality_data = quality_response.json()

        # Health should reference same metrics
        health_records = health_data["components"]["data_quality"]["total_records_last_24h"]
        quality_records = quality_data["summary"]["total_records"]

        assert health_records == quality_records


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
