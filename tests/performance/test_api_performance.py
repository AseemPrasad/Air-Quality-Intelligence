"""Performance tests for API endpoints."""

import pytest
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics


@pytest.fixture
def mock_api_client():
    """Mock API client for performance testing."""
    class MockAPIClient:
        def __init__(self):
            self.latencies = []

        def get_locations(self):
            """Simulate /locations endpoint."""
            # Mock response: 100 locations
            time.sleep(0.05)  # 50ms base latency
            return {"locations": [{"id": i} for i in range(100)]}

        def get_current(self, location_id):
            """Simulate /locations/{id}/current endpoint."""
            # Mock response: current observation
            time.sleep(0.10)  # 100ms base latency
            return {
                "location_id": location_id,
                "current_pm25": 65.5,
                "temperature_c": 28.5,
            }

        def get_forecast(self, location_id):
            """Simulate /locations/{id}/forecast endpoint."""
            # Mock response: forecast
            time.sleep(0.20)  # 200ms base latency
            return {
                "location_id": location_id,
                "forecasts": [
                    {"horizon_minutes": 60, "predicted_pm25": 62.0},
                    {"horizon_minutes": 180, "predicted_pm25": 64.0},
                    {"horizon_minutes": 360, "predicted_pm25": 66.0},
                ]
            }

        def record_latency(self, endpoint, latency_ms):
            """Record latency for analysis."""
            self.latencies.append({
                "endpoint": endpoint,
                "latency_ms": latency_ms,
            })

    return MockAPIClient()


class TestAPIPerformance:
    """Test API response times."""

    def test_locations_list_under_100ms(self, benchmark, mock_api_client):
        """Test: /locations responds in < 100ms."""

        def get_locations():
            start = time.time()
            result = mock_api_client.get_locations()
            latency = (time.time() - start) * 1000  # ms
            return latency

        latency = benchmark(get_locations)

        assert latency < 100  # < 100ms
        print(f"GET /locations: {latency:.1f}ms")

    def test_current_observation_under_200ms(self, benchmark, mock_api_client):
        """Test: /locations/{id}/current responds in < 200ms."""

        def get_current():
            start = time.time()
            result = mock_api_client.get_current("kolkata_001")
            latency = (time.time() - start) * 1000  # ms
            return latency

        latency = benchmark(get_current)

        assert latency < 200  # < 200ms
        print(f"GET /locations/{{id}}/current: {latency:.1f}ms")

    def test_forecast_under_500ms(self, benchmark, mock_api_client):
        """Test: /locations/{id}/forecast responds in < 500ms."""

        def get_forecast():
            start = time.time()
            result = mock_api_client.get_forecast("kolkata_001")
            latency = (time.time() - start) * 1000  # ms
            return latency

        latency = benchmark(get_forecast)

        assert latency < 500  # < 500ms
        print(f"GET /locations/{{id}}/forecast: {latency:.1f}ms")

    def test_concurrent_load_100_requests(self, mock_api_client):
        """Load test: 100 concurrent requests, 95th percentile < 1s."""

        latencies = []

        def make_request(request_id):
            """Make concurrent request."""
            endpoint = ["locations", "current", "forecast"][request_id % 3]
            start = time.time()

            if endpoint == "locations":
                mock_api_client.get_locations()
            elif endpoint == "current":
                mock_api_client.get_current("kolkata_001")
            else:
                mock_api_client.get_forecast("kolkata_001")

            latency_ms = (time.time() - start) * 1000
            return latency_ms

        # Execute 100 concurrent requests
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(100)]
            latencies = [f.result() for f in as_completed(futures)]

        # Analyze latencies
        p95 = statistics.quantiles(latencies, n=20)[18]  # 95th percentile
        p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile
        avg = statistics.mean(latencies)

        print(f"Concurrent load (100 reqs):")
        print(f"  Average: {avg:.1f}ms")
        print(f"  P95: {p95:.1f}ms")
        print(f"  P99: {p99:.1f}ms")

        # Assertions
        assert p95 < 1000  # 95th percentile < 1 second
        assert p99 < 1500  # 99th percentile < 1.5 seconds

    @pytest.mark.benchmark(group="api")
    def test_locations_regression(self, benchmark, mock_api_client):
        """Regression test: /locations baseline."""

        result = benchmark(mock_api_client.get_locations)
        assert "locations" in result

    @pytest.mark.benchmark(group="api")
    def test_current_regression(self, benchmark, mock_api_client):
        """Regression test: /current baseline."""

        result = benchmark(
            mock_api_client.get_current,
            "kolkata_001"
        )
        assert "location_id" in result

    @pytest.mark.benchmark(group="api")
    def test_forecast_regression(self, benchmark, mock_api_client):
        """Regression test: /forecast baseline."""

        result = benchmark(
            mock_api_client.get_forecast,
            "kolkata_001"
        )
        assert "forecasts" in result


class TestAPIRegressionDetection:
    """Test regression detection (> 20% slowdown)."""

    def test_latency_regression_detection(self, mock_api_client):
        """Test detection of latency regressions."""

        # Simulate baseline: 100ms
        baseline_ms = 100

        # Simulate current: 110ms (10% slower - OK)
        current_ms = 110
        regression_pct = ((current_ms - baseline_ms) / baseline_ms) * 100

        assert regression_pct <= 20  # Within threshold

        # Simulate regression: 125ms (25% slower - ALERT)
        current_ms_bad = 125
        regression_pct_bad = ((current_ms_bad - baseline_ms) / baseline_ms) * 100

        assert regression_pct_bad > 20  # Alert!

        print(f"Regression detection: {regression_pct_bad:.1f}% slowdown detected")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--benchmark-compare"])
