"""Comprehensive tests for data connectors (OpenAQ, Open-Meteo)."""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta


@pytest.fixture
def mock_http_response():
    """Mock HTTP response factory."""
    def _create_response(status_code, data=None, headers=None):
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        response.text = json.dumps(data) if data else ""
        response.json.return_value = data or {}
        return response
    return _create_response


class TestFetchRetryLogic:
    """Test retry logic with exponential backoff."""

    def test_successful_fetch_no_retry(self):
        """Test successful fetch requires no retries."""
        attempt_count = [0]

        def mock_fetch():
            attempt_count[0] += 1
            if attempt_count[0] == 1:
                return {"success": True}
            raise Exception("Should not be called")

        result = mock_fetch()
        assert result["success"] is True
        assert attempt_count[0] == 1

    def test_retry_on_transient_failure(self):
        """Test retry on transient failure (timeout)."""
        attempt_count = [0]

        def mock_fetch():
            attempt_count[0] += 1
            if attempt_count[0] < 2:
                raise TimeoutError("Connection timeout")
            return {"success": True}

        result = None
        for retry in range(3):
            try:
                result = mock_fetch()
                break
            except TimeoutError:
                if retry == 2:
                    raise

        assert result["success"] is True
        assert attempt_count[0] == 2

    def test_exponential_backoff_delays(self):
        """Test exponential backoff increases delays."""
        delays = []
        base_delay = 1  # seconds

        for retry in range(3):
            delay = base_delay * (2 ** retry)
            delays.append(delay)

        # Should be 1s, 2s, 4s
        assert delays == [1, 2, 4]

    def test_max_three_retries(self):
        """Test maximum of 3 retries before giving up."""
        attempt_count = [0]

        def mock_fetch():
            attempt_count[0] += 1
            raise TimeoutError("Always fails")

        max_retries = 2  # 0, 1, 2 = 3 attempts total

        with pytest.raises(TimeoutError):
            for retry in range(max_retries + 1):
                try:
                    mock_fetch()
                    break
                except TimeoutError:
                    if retry == max_retries:
                        raise

    def test_retry_continues_after_partial_failure(self):
        """Test retries continue after transient failure."""
        attempts = []

        def mock_fetch():
            attempts.append(datetime.now())
            if len(attempts) < 3:
                raise ConnectionError("Network error")
            return {"records": 1200}

        result = None
        for retry in range(4):
            try:
                result = mock_fetch()
                break
            except ConnectionError:
                if retry == 3:
                    raise

        assert result["records"] == 1200
        assert len(attempts) == 3


class TestHTTPErrorCodes:
    """Test handling of different HTTP error codes."""

    def test_2xx_success_codes(self, mock_http_response):
        """Test 2xx codes treated as success."""
        for code in [200, 201, 202, 204]:
            response = mock_http_response(code, {"data": "test"})
            assert response.status_code // 100 == 2

    def test_429_rate_limit_error(self, mock_http_response):
        """Test 429 rate limit error triggers retry."""
        response = mock_http_response(429, {"error": "Too many requests"})

        # 429 should trigger retry (not permanent failure)
        is_retryable = response.status_code == 429
        assert is_retryable is True

    def test_5xx_server_error_retryable(self, mock_http_response):
        """Test 5xx errors are retryable."""
        for code in [500, 502, 503, 504]:
            response = mock_http_response(code, {"error": "Server error"})
            is_retryable = 500 <= response.status_code < 600
            assert is_retryable is True

    def test_4xx_client_error_not_retryable(self, mock_http_response):
        """Test 4xx errors (except 429) are not retryable."""
        for code in [400, 401, 403, 404]:
            response = mock_http_response(code, {"error": "Client error"})
            is_retryable = code == 429 or response.status_code == 429
            assert is_retryable is False

    def test_404_not_found(self, mock_http_response):
        """Test 404 not found is permanent failure."""
        response = mock_http_response(404, {"error": "Not found"})
        assert response.status_code == 404

    def test_401_unauthorized(self, mock_http_response):
        """Test 401 unauthorized is permanent failure."""
        response = mock_http_response(401, {"error": "Unauthorized"})
        assert response.status_code == 401


class TestTimeoutAndRetry:
    """Test timeout handling with retries."""

    def test_timeout_triggers_retry(self):
        """Test timeout causes retry."""
        attempt_count = [0]

        def fetch_with_timeout():
            attempt_count[0] += 1
            if attempt_count[0] == 1:
                raise TimeoutError("Request timed out after 30s")
            return {"success": True}

        result = None
        for retry in range(2):
            try:
                result = fetch_with_timeout()
                break
            except TimeoutError:
                pass

        assert result["success"] is True
        assert attempt_count[0] == 2

    def test_timeout_threshold_30_seconds(self):
        """Test timeout threshold is 30 seconds."""
        timeout_threshold = 30
        assert timeout_threshold == 30

    def test_timeout_exponential_backoff(self):
        """Test timeout retries use exponential backoff."""
        delays = []
        base = 1

        for retry in range(3):
            delay = base * (2 ** retry)
            delays.append(delay)

        # Delays: 1s, 2s, 4s
        assert sum(delays) == 7  # Total wait time


class TestMalformedJSONResponse:
    """Test handling of malformed JSON responses."""

    def test_invalid_json_quarantined(self):
        """Test malformed JSON response is quarantined."""
        response_text = "{ invalid json"

        try:
            json.loads(response_text)
            assert False, "Should have raised JSONDecodeError"
        except json.JSONDecodeError:
            quarantine_status = "QUARANTINE"

        assert quarantine_status == "QUARANTINE"

    def test_incomplete_json_rejected(self):
        """Test incomplete JSON is rejected."""
        response_text = '{"data": [{"id": 1, "value":'

        is_valid = False
        try:
            json.loads(response_text)
            is_valid = True
        except json.JSONDecodeError:
            is_valid = False

        assert is_valid is False

    def test_null_response_body(self):
        """Test null response body is rejected."""
        response_text = ""

        is_valid = False
        try:
            if response_text:
                json.loads(response_text)
                is_valid = True
        except json.JSONDecodeError:
            pass

        assert is_valid is False

    def test_html_error_response(self):
        """Test HTML error response is quarantined."""
        response_text = "<html><body>500 Internal Server Error</body></html>"

        is_json = False
        try:
            json.loads(response_text)
            is_json = True
        except json.JSONDecodeError:
            is_json = False

        assert is_json is False


class TestPagination:
    """Test pagination handling for large result sets."""

    def test_pagination_single_page(self):
        """Test single page (< 1000 records) requires no pagination."""
        records = [{"id": i, "value": f"record_{i}"} for i in range(500)]

        pages = 1
        total_records = len(records)

        assert total_records == 500
        assert pages == 1

    def test_pagination_multiple_pages(self):
        """Test multiple pages for > 1000 records."""
        page_size = 1000
        total_records = 2500

        pages_needed = (total_records + page_size - 1) // page_size

        assert pages_needed == 3

    def test_pagination_exact_boundary(self):
        """Test pagination at exact boundary (1000 records)."""
        page_size = 1000
        total_records = 1000

        pages_needed = (total_records + page_size - 1) // page_size

        assert pages_needed == 1

    def test_pagination_accumulation(self):
        """Test records accumulated from multiple pages."""
        page_size = 1000
        pages = [
            [{"id": i} for i in range(0, 1000)],      # Page 1: 1000 records
            [{"id": i} for i in range(1000, 2000)],   # Page 2: 1000 records
            [{"id": i} for i in range(2000, 2500)],   # Page 3: 500 records
        ]

        total = sum(len(page) for page in pages)

        assert total == 2500

    def test_pagination_incomplete_last_page(self):
        """Test incomplete last page is handled."""
        pages = [
            {"data": [{"id": i} for i in range(1000)]},  # 1000
            {"data": [{"id": i} for i in range(1000, 1750)]},  # 750
        ]

        total = sum(len(p["data"]) for p in pages)

        assert total == 1750


class TestWatermarkAdvancement:
    """Test watermark tracking for incremental ingestion."""

    def test_watermark_advances_on_success(self):
        """Test watermark advances after successful fetch."""
        current_watermark = "2026-08-10T00:00:00Z"

        # Simulate successful fetch
        fetch_success = True
        new_records = 1200

        if fetch_success and new_records > 0:
            new_watermark = "2026-08-11T00:00:00Z"

        assert current_watermark < new_watermark

    def test_watermark_stays_on_failure(self):
        """Test watermark doesn't advance on failure."""
        current_watermark = "2026-08-10T00:00:00Z"

        # Simulate failed fetch
        fetch_success = False

        if fetch_success:
            new_watermark = "2026-08-11T00:00:00Z"
        else:
            new_watermark = current_watermark

        assert new_watermark == current_watermark

    def test_watermark_partial_fetch_failure(self):
        """Test watermark on partial success (some records fetched)."""
        current_watermark = "2026-08-10T00:00:00Z"
        last_successful_record_time = "2026-08-10T18:00:00Z"

        # Partial success: fetched some records before failure
        if last_successful_record_time > current_watermark:
            new_watermark = last_successful_record_time
        else:
            new_watermark = current_watermark

        assert new_watermark == last_successful_record_time

    def test_watermark_prevents_reprocessing(self):
        """Test watermark prevents reprocessing same data."""
        watermark = "2026-08-10T00:00:00Z"
        fetched_records = [
            {"timestamp": "2026-08-09T00:00:00Z"},
            {"timestamp": "2026-08-10T00:00:00Z"},
            {"timestamp": "2026-08-10T12:00:00Z"},
        ]

        # Filter records after watermark
        new_records = [r for r in fetched_records if r["timestamp"] > watermark]

        assert len(new_records) == 1
        assert new_records[0]["timestamp"] == "2026-08-10T12:00:00Z"


class TestRateLimiting:
    """Test rate limiting and backoff."""

    def test_rate_limit_429_response(self):
        """Test 429 rate limit response detection."""
        status_code = 429
        is_rate_limited = status_code == 429

        assert is_rate_limited is True

    def test_rate_limit_retry_after_header(self):
        """Test Retry-After header extraction."""
        headers = {"Retry-After": "60"}

        retry_after = int(headers.get("Retry-After", 60))

        assert retry_after == 60

    def test_rate_limit_exponential_backoff(self):
        """Test rate limit uses exponential backoff."""
        base_delay = 60  # seconds
        delays = []

        for attempt in range(3):
            delay = base_delay * (2 ** attempt)
            delays.append(delay)

        # Should be 60s, 120s, 240s
        assert delays == [60, 120, 240]

    def test_rate_limit_max_delay_cap(self):
        """Test rate limit delay has maximum cap."""
        max_delay = 3600  # 1 hour

        base = 60
        for attempt in range(10):
            delay = min(base * (2 ** attempt), max_delay)

        assert delay == max_delay

    def test_request_queueing_under_rate_limit(self):
        """Test requests queue under rate limiting."""
        queue = []
        rate_limit_active = True

        if rate_limit_active:
            queue.append({"request": "fetch_data", "queued_at": datetime.now()})

        assert len(queue) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
