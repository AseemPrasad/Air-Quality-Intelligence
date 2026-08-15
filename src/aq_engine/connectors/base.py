"""Base connector abstraction for data source integrations.

Provides common functionality for air quality and weather connectors:
- HTTP request/response handling with retry logic
- Rate limiting (token bucket)
- Watermark management for incremental ingestion
- Response caching (optional)
- Thread-safe session reuse
- Comprehensive error logging
"""

import abc
import hashlib
import logging
import random
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from abc import abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry as UrllibRetry

from aq_engine.common import (
    ensure_utc,
    log_operation,
    StructuredLogger,
    IngestionFailed,
    DataContractViolation,
)
from aq_engine.connectors.models import (
    ConnectorConfig,
    SourceResponse,
    ParsedRecord,
    Watermark,
    IngestionRunMetadata,
)


logger = logging.getLogger(__name__)
slog = StructuredLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter (thread-safe).

    Implements the token bucket algorithm to limit request rates.
    Useful for API rate limiting when max_concurrent_requests is 1.

    Example:
        >>> bucket = TokenBucket(capacity=60, refill_rate=1.0)
        >>> while not bucket.acquire():
        ...     time.sleep(0.1)  # Wait for tokens to refill
    """

    def __init__(self, capacity: int, refill_rate: float):
        """Initialize token bucket.

        Args:
            capacity: Maximum tokens (refills per minute for rate limiting).
            refill_rate: Tokens added per second.
        """
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens without blocking.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens acquired, False if insufficient tokens.
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            refilled = elapsed * self._refill_rate
            self._tokens = min(self._capacity, self._tokens + refilled)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_for_tokens(self, tokens: int = 1, max_wait_seconds: float = 60.0) -> bool:
        """Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire.
            max_wait_seconds: Maximum time to wait.

        Returns:
            True if tokens acquired within timeout, False if timeout.
        """
        start = time.time()
        while not self.acquire(tokens):
            if time.time() - start > max_wait_seconds:
                return False
            time.sleep(0.1)  # Poll every 100ms
        return True


class BaseConnector(abc.ABC):
    """Abstract base class for data source connectors.

    Provides common functionality for fetching, parsing, and storing data
    from external APIs (air quality, weather, etc.). Subclasses must
    implement fetch(), parse(), validate_source_response(), and write_raw().

    Features:
    - Retry logic with exponential backoff + jitter
    - Rate limiting (token bucket)
    - Watermark management for incremental ingestion
    - Thread-safe session reuse
    - Comprehensive error logging
    - Response caching (optional)

    Example:
        >>> connector = OpenAQConnector(config)
        >>> run_id = connector.ingest(start_date, end_date)
        >>> # Connector automatically handles retries, logging, watermarks
    """

    def __init__(
        self,
        config: ConnectorConfig,
        session: Optional[requests.Session] = None,
        response_cache_dir: Optional[Path] = None,
    ):
        """Initialize connector.

        Args:
            config: Connector configuration.
            session: Optional requests.Session for reuse (useful for testing).
            response_cache_dir: Optional directory for caching responses (development).

        Raises:
            ValueError: If config is invalid.
        """
        if not config.source_name or not config.base_url:
            raise ValueError("Config must have source_name and base_url")

        self.config = config
        self._session = session or self._create_session()
        self._response_cache_dir = response_cache_dir
        self._rate_limiter = TokenBucket(
            capacity=config.rate_limit.requests_per_minute,
            refill_rate=config.rate_limit.requests_per_minute / 60.0,
        )
        self._lock = threading.Lock()

    @staticmethod
    def _create_session() -> requests.Session:
        """Create a thread-safe requests session with retry adapter.

        Returns:
            Configured Session with retry logic at HTTP transport layer.
        """
        session = requests.Session()

        # Retry adapter for HTTP layer (handles connection errors, timeouts)
        retry_strategy = UrllibRetry(
            total=3,
            backoff_factor=1,  # Exponential: 1s, 2s, 4s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def ingest(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        watermark: Optional[Watermark] = None,
        lookback_hours: float = 6.0,
    ) -> Tuple[str, IngestionRunMetadata]:
        """Perform full ingestion run: fetch, parse, validate, write, record.

        Handles retry logic, watermark management, and error recovery.

        Args:
            start_time: Query start time (optional; uses watermark or lookback).
            end_time: Query end time (defaults to now).
            watermark: Watermark for incremental ingestion.
            lookback_hours: Default lookback if no watermark (hours).

        Returns:
            Tuple of (run_id, run_metadata).

        Raises:
            IngestionFailed: If ingestion fails after retries.
        """
        run_id = str(uuid.uuid4())

        # Determine query window
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        end_time = ensure_utc(end_time)

        if start_time is None:
            if watermark is not None:
                start_time = watermark.get_query_start(lookback_hours)
            else:
                from aq_engine.common import hours_ago

                start_time = hours_ago(int(lookback_hours))
        start_time = ensure_utc(start_time)

        # Initialize run metadata
        run_metadata = IngestionRunMetadata(
            run_id=run_id,
            source_id=0,  # Will be set by subclass if needed
            started_at=datetime.now(timezone.utc),
            status="running",
            requested_start=start_time,
            requested_end=end_time,
        )

        with log_operation(
            f"ingest_{self.config.source_name}",
            {
                "source": self.config.source_name,
                "run_id": run_id,
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
        ):
            try:
                # Fetch data from source
                response = self._fetch_with_retry(start_time, end_time)
                run_metadata.records_received = 1  # Will be updated by subclass

                # Validate source response
                self.validate_source_response(response)

                # Parse into canonical records
                parsed_records = self.parse(response, start_time, end_time)
                logger.debug(f"Parsed {len(parsed_records)} records")

                # Write to storage
                written_count, rejected_count = self.write_raw(parsed_records, run_id)
                run_metadata.records_written = written_count
                run_metadata.records_rejected = rejected_count

                # Record successful run
                self.record_run(run_metadata, success=True)

                run_metadata.status = "success"
                run_metadata.finished_at = datetime.now(timezone.utc)

                slog.ingestion_complete(
                    self.config.source_name,
                    records_received=run_metadata.records_received,
                    records_written=written_count,
                    records_rejected=rejected_count,
                )

                return run_id, run_metadata

            except Exception as e:
                # Record failed run (watermark NOT advanced)
                run_metadata.status = "failed"
                run_metadata.finished_at = datetime.now(timezone.utc)
                run_metadata.error_message = str(e)

                self.record_run(run_metadata, success=False)

                slog.ingestion_error(self.config.source_name, error=str(e))
                logger.error(f"Ingestion failed: {e}", exc_info=True)

                raise IngestionFailed(
                    f"Ingestion from {self.config.source_name} failed",
                    context={
                        "source": self.config.source_name,
                        "run_id": run_id,
                        "error": str(e),
                    },
                ) from e

    def _fetch_with_retry(
        self, start_time: datetime, end_time: datetime, attempt: int = 0
    ) -> SourceResponse:
        """Fetch data from source with retry logic.

        Implements exponential backoff + jitter for transient errors.

        Args:
            start_time: Query window start.
            end_time: Query window end.
            attempt: Current retry attempt (internal).

        Returns:
            HTTP response from source.

        Raises:
            IngestionFailed: If all retries exhausted or permanent error.
        """
        try:
            # Apply rate limiting
            if not self._rate_limiter.wait_for_tokens(max_wait_seconds=60.0):
                raise IngestionFailed(
                    "Rate limiter timeout",
                    context={"source": self.config.source_name},
                )

            # Fetch (subclass implementation)
            response = self.fetch(start_time, end_time)

            # Permanent error? Fail immediately
            if response.is_permanent_error():
                raise IngestionFailed(
                    f"Permanent HTTP error {response.status_code}",
                    context={
                        "source": self.config.source_name,
                        "status_code": response.status_code,
                    },
                )

            return response

        except (requests.Timeout, requests.ConnectionError) as e:
            # Timeout or connection error: retry
            if attempt < self.config.retry.max_attempts:
                delay = self._get_retry_delay(attempt)
                logger.warning(
                    f"Timeout/connection error (attempt {attempt + 1}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)
                return self._fetch_with_retry(start_time, end_time, attempt=attempt + 1)
            else:
                raise IngestionFailed(
                    f"Timeout/connection error after {self.config.retry.max_attempts} attempts",
                    context={"source": self.config.source_name},
                ) from e

        except IngestionFailed:
            # Already handled or permanent error
            raise

    def _get_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter.

        Args:
            attempt: Retry attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        if attempt >= len(self.config.retry.delays_seconds):
            delay = self.config.retry.delays_seconds[-1]
        else:
            delay = self.config.retry.delays_seconds[attempt]

        # Add jitter: ±10% of delay
        jitter = delay * self.config.retry.jitter_fraction
        jittered_delay = delay + random.uniform(-jitter, jitter)

        return max(0.1, jittered_delay)  # Minimum 100ms

    @abstractmethod
    def fetch(self, start_time: datetime, end_time: datetime) -> SourceResponse:
        """Fetch data from external source.

        Must be implemented by subclasses to make actual API request.

        Args:
            start_time: Query window start (UTC).
            end_time: Query window end (UTC).

        Returns:
            HTTP response from source.

        Raises:
            requests.Timeout: On timeout.
            requests.ConnectionError: On connection error.
            IngestionFailed: On permanent HTTP errors.
        """
        pass

    @abstractmethod
    def parse(
        self, response: SourceResponse, start_time: datetime, end_time: datetime
    ) -> List[ParsedRecord]:
        """Parse source response into canonical records.

        Must be implemented by subclasses to extract observations.

        Args:
            response: HTTP response from fetch().
            start_time: Query window start.
            end_time: Query window end.

        Returns:
            List of canonical ParsedRecord objects.

        Raises:
            DataContractViolation: If response format is invalid.
        """
        pass

    def validate_source_response(self, response: SourceResponse) -> None:
        """Validate that source response is well-formed.

        Default implementation checks status code. Subclasses can override
        to add format-specific validation.

        Args:
            response: HTTP response to validate.

        Raises:
            IngestionFailed: If response indicates error.
        """
        if not response.is_success():
            raise IngestionFailed(
                f"HTTP {response.status_code}: {response.body}",
                context={
                    "source": self.config.source_name,
                    "status_code": response.status_code,
                },
            )

    @abstractmethod
    def write_raw(self, records: List[ParsedRecord], run_id: str) -> Tuple[int, int]:
        """Write parsed records to raw data storage.

        Must be implemented by subclasses to persist data.

        Args:
            records: Canonical records to write.
            run_id: Ingestion run identifier.

        Returns:
            Tuple of (records_written, records_rejected).

        Raises:
            StorageError: If write fails.
        """
        pass

    @abstractmethod
    def record_run(self, metadata: IngestionRunMetadata, success: bool) -> None:
        """Record ingestion run in control plane.

        Must be implemented by subclasses to update PostgreSQL metadata.

        Args:
            metadata: Run metadata.
            success: Whether run succeeded (False = watermark not advanced).

        Raises:
            DatabaseError: If metadata write fails.
        """
        pass

    def _get_cached_response(self, url: str) -> Optional[SourceResponse]:
        """Retrieve cached response if caching enabled.

        Args:
            url: Request URL.

        Returns:
            Cached SourceResponse or None if not cached/caching disabled.
        """
        if self._response_cache_dir is None:
            return None

        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = self._response_cache_dir / f"{cache_key}.json"

        if cache_path.exists():
            import json

            try:
                with open(cache_path) as f:
                    cached = json.load(f)
                logger.debug(f"Cache hit for {url}")
                return SourceResponse(**cached)
            except Exception as e:
                logger.warning(f"Cache read failed: {e}")
                return None

        return None

    def _cache_response(self, url: str, response: SourceResponse) -> None:
        """Cache response for development/testing.

        Args:
            url: Request URL.
            response: SourceResponse to cache.
        """
        if self._response_cache_dir is None:
            return

        self._response_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = self._response_cache_dir / f"{cache_key}.json"

        try:
            import json

            with open(cache_path, "w") as f:
                json.dump(
                    {
                        "status_code": response.status_code,
                        "headers": response.headers,
                        "body": response.body,
                        "elapsed_seconds": response.elapsed_seconds,
                        "timestamp": response.timestamp.isoformat(),
                        "raw_payload_hash": response.raw_payload_hash,
                    },
                    f,
                )
            logger.debug(f"Cached response for {url}")
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
