"""Data models for connectors.

Defines configuration, request/response schemas, and watermark structures.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
import hashlib


@dataclass
class RetryConfig:
    """Retry policy configuration.

    Attributes:
        max_attempts: Maximum number of retry attempts (including initial try).
        delays_seconds: List of delays between retries (exponential backoff).
        transient_status_codes: HTTP status codes to retry on.
        jitter_fraction: Fraction of delay to add as random jitter (0.0-1.0).
    """

    max_attempts: int = 3
    delays_seconds: List[float] = field(default_factory=lambda: [2.0, 4.0, 8.0])
    transient_status_codes: List[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])
    jitter_fraction: float = 0.1  # 10% jitter


@dataclass
class RateLimitConfig:
    """Rate limiting configuration (token bucket algorithm).

    Attributes:
        requests_per_minute: Maximum requests per minute.
        max_parallel_requests: Maximum concurrent requests.
    """

    requests_per_minute: int = 60
    max_parallel_requests: int = 1


@dataclass
class ConnectorConfig:
    """Connector configuration.

    Attributes:
        source_name: Source identifier (e.g., "openaq", "open_meteo").
        source_type: Type of source (e.g., "air_quality", "weather").
        base_url: API base URL.
        timeout_seconds: Request timeout.
        retry: Retry policy configuration.
        rate_limit: Rate limiting configuration.
    """

    source_name: str
    source_type: str
    base_url: str
    timeout_seconds: float = 30.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)


@dataclass
class SourceResponse:
    """HTTP response from data source.

    Attributes:
        status_code: HTTP status code.
        headers: Response headers.
        body: Response body (raw bytes or JSON).
        elapsed_seconds: Request duration.
        timestamp: When response was received (UTC).
        raw_payload_hash: SHA256 hash of response body (for deduplication).
    """

    status_code: int
    headers: Dict[str, str]
    body: Any  # bytes or dict (JSON)
    elapsed_seconds: float
    timestamp: datetime
    raw_payload_hash: Optional[str] = None

    def __post_init__(self):
        """Compute raw_payload_hash if not provided."""
        if self.raw_payload_hash is None and self.body is not None:
            if isinstance(self.body, bytes):
                payload = self.body
            elif isinstance(self.body, str):
                payload = self.body.encode()
            else:
                import json

                payload = json.dumps(self.body, sort_keys=True).encode()
            self.raw_payload_hash = hashlib.sha256(payload).hexdigest()

    def is_success(self) -> bool:
        """Check if response indicates success (2xx status)."""
        return 200 <= self.status_code < 300

    def is_transient_error(self, transient_codes: List[int]) -> bool:
        """Check if response indicates transient error (retry-able)."""
        return self.status_code in transient_codes

    def is_permanent_error(self) -> bool:
        """Check if response indicates permanent error (don't retry)."""
        return 400 <= self.status_code < 500 and self.status_code != 429


@dataclass
class ParsedRecord:
    """Canonical record parsed from source response.

    Represents a single observation (air quality or weather) with metadata.

    Attributes:
        source: Source identifier.
        record_type: Type of record ("air_quality" or "weather").
        data: Canonical record data (dict).
        measurement_key: Idempotency key (SHA256 of source+station+sensor+observed_at).
        raw_payload_hash: Hash of raw source data.
        ingestion_timestamp: When this record was ingested.
    """

    source: str
    record_type: str
    data: Dict[str, Any]
    measurement_key: str
    raw_payload_hash: str
    ingestion_timestamp: datetime


@dataclass
class Watermark:
    """Tracks ingestion progress per source.

    Stores last successful observation time and ingestion run time
    to determine query windows for incremental ingestion.

    Attributes:
        source_id: Source identifier.
        last_successful_event_time: Last observation timestamp successfully ingested.
        last_ingestion_time: When last successful ingestion completed.
        last_attempted_time: When last ingestion attempt was made (even if failed).
    """

    source_id: int
    last_successful_event_time: Optional[datetime] = None
    last_ingestion_time: Optional[datetime] = None
    last_attempted_time: Optional[datetime] = None

    def get_query_start(self, default_lookback_hours: float = 6) -> datetime:
        """Determine query start time based on watermark.

        Falls back to default lookback if no watermark exists.

        Args:
            default_lookback_hours: Lookback hours if no watermark.

        Returns:
            Query start time (UTC).
        """
        from datetime import timedelta

        if self.last_successful_event_time is not None:
            return self.last_successful_event_time

        # Fallback: lookback from now
        from aq_engine.common import hours_ago

        return hours_ago(int(default_lookback_hours))


@dataclass
class IngestionRunMetadata:
    """Metadata for an ingestion run.

    Tracks run state for auditing and recovery.

    Attributes:
        run_id: Unique run identifier (UUID).
        source_id: Source being ingested.
        started_at: Run start time (UTC).
        finished_at: Run completion time (UTC, None if running).
        status: Run status ("running", "success", "failed", "partial").
        requested_start: Query window start time.
        requested_end: Query window end time.
        records_received: Total records fetched from source.
        records_written: Records successfully written to storage.
        records_rejected: Records rejected during validation.
        error_message: Error details if status is "failed".
    """

    run_id: str
    source_id: int
    started_at: datetime
    status: str  # "running", "success", "failed", "partial"
    requested_start: Optional[datetime] = None
    requested_end: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    records_received: int = 0
    records_written: int = 0
    records_rejected: int = 0
    error_message: Optional[str] = None

    def is_complete(self) -> bool:
        """Check if run has finished."""
        return self.status in ("success", "failed", "partial") and self.finished_at is not None
