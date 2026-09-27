# Connector Abstraction - Deliverables Summary

## ✓ COMPLETE (3 Files, 776 Lines)

### Files Created

1. **src/aq_engine/connectors/models.py** (207 lines, 6.7K)
2. **src/aq_engine/connectors/base.py** (529 lines, 18K)
3. **src/aq_engine/connectors/__init__.py** (40 lines, 1.1K)

---

## 1. Data Models (models.py)

### Dataclasses & Configuration

#### `@dataclass RetryConfig`
```python
max_attempts: int = 3
delays_seconds: List[float] = [2.0, 4.0, 8.0]  # Exponential backoff
transient_status_codes: List[int] = [429, 500, 502, 503, 504]
jitter_fraction: float = 0.1  # ±10% random jitter
```
- Configurable retry policy
- Exponential backoff: 2s, 4s, 8s delays
- Transient status codes: 429 (rate limit), 5xx (server errors)
- Jitter prevents thundering herd

#### `@dataclass RateLimitConfig`
```python
requests_per_minute: int = 60
max_parallel_requests: int = 1
```
- Token bucket rate limiting
- Respects API rate limits
- Supports concurrent requests

#### `@dataclass ConnectorConfig`
```python
source_name: str           # "openaq", "open_meteo"
source_type: str           # "air_quality", "weather"
base_url: str              # API endpoint
timeout_seconds: float = 30.0
retry: RetryConfig
rate_limit: RateLimitConfig
```
- Full connector configuration
- Used by subclasses (OpenAQConnector, OpenMeteoConnector)
- Loaded from YAML configs

#### `@dataclass SourceResponse`
```python
status_code: int
headers: Dict[str, str]
body: Any  # bytes or dict (JSON)
elapsed_seconds: float
timestamp: datetime
raw_payload_hash: Optional[str]  # SHA256 for deduplication
```
- Wraps HTTP response
- Auto-computes payload hash
- Methods: `is_success()`, `is_transient_error()`, `is_permanent_error()`

#### `@dataclass ParsedRecord`
```python
source: str
record_type: str  # "air_quality" or "weather"
data: Dict[str, Any]  # Canonical record data
measurement_key: str  # SHA256 idempotency key
raw_payload_hash: str
ingestion_timestamp: datetime
```
- Canonical record representation
- `measurement_key` = SHA256(source+station+sensor+observed_at)
- Ensures idempotency during ingestion

#### `@dataclass Watermark`
```python
source_id: int
last_successful_event_time: Optional[datetime]  # Last observation timestamp
last_ingestion_time: Optional[datetime]        # When last run succeeded
last_attempted_time: Optional[datetime]         # Even if failed
```
- Tracks ingestion progress per source
- `get_query_start(lookback_hours)` → Determine query window
- Falls back to lookback if no watermark

#### `@dataclass IngestionRunMetadata`
```python
run_id: str  # UUID
source_id: int
started_at: datetime
status: str  # "running", "success", "failed", "partial"
requested_start: datetime
requested_end: datetime
records_received: int
records_written: int
records_rejected: int
error_message: Optional[str]
```
- Auditable run state
- `is_complete()` checks if finished
- Never advance watermark if status != "success"

---

## 2. Base Connector (base.py)

### TokenBucket (Rate Limiter)

```python
class TokenBucket:
    """Thread-safe rate limiting using token bucket algorithm."""
    
    def __init__(self, capacity: int, refill_rate: float)
    def acquire(tokens: int = 1) -> bool
    def wait_for_tokens(tokens: int = 1, max_wait_seconds: float = 60.0) -> bool
```

**Features:**
- Token bucket algorithm (requests per minute)
- Thread-safe (locks around critical sections)
- Non-blocking `acquire()` + blocking `wait_for_tokens()`
- Respects API rate limits gracefully

**Example:**
```python
bucket = TokenBucket(capacity=60, refill_rate=1.0)  # 60 req/min
if not bucket.wait_for_tokens():
    raise IngestionFailed("Rate limiter timeout")
```

### BaseConnector (Abstract)

```python
class BaseConnector(abc.ABC):
    """Abstract connector for data source integration."""
```

#### Constructor
```python
def __init__(
    self,
    config: ConnectorConfig,
    session: Optional[requests.Session] = None,
    response_cache_dir: Optional[Path] = None
)
```
- `config`: Connector configuration (source_name, base_url, retry, rate_limit)
- `session`: Optional reusable session (for testing/thread reuse)
- `response_cache_dir`: Optional cache for development (stores responses as JSON)

#### Public Methods

##### `ingest(start_time, end_time, watermark, lookback_hours) → Tuple[run_id, metadata]`

Performs full ingestion pipeline:

1. **Determine query window**
   - If `start_time` not provided: use watermark or lookback
   - If `end_time` not provided: use now
   - Ensures UTC timezone

2. **Fetch data** → `_fetch_with_retry()`
   - Rate limiting via TokenBucket
   - Retry logic for transient errors
   - Exponential backoff + jitter

3. **Validate** → `validate_source_response()`
   - Check HTTP status code
   - Format-specific validation (subclass)

4. **Parse** → `parse()`
   - Extract canonical records from response
   - Compute measurement keys (idempotency)

5. **Write** → `write_raw()`
   - Persist to Parquet storage
   - Returns (written_count, rejected_count)

6. **Record** → `record_run()`
   - Update PostgreSQL metadata
   - Watermark only advanced if success=True

7. **Error handling**
   - Logs all errors with context
   - Records failed run without advancing watermark
   - Raises `IngestionFailed` with full traceback

**Example:**
```python
with log_operation("ingest_openaq"):
    run_id, metadata = connector.ingest(
        start_time=datetime(2026, 8, 15),
        watermark=watermark,
        lookback_hours=6
    )
    print(f"Ingested {metadata.records_written} records")
```

##### `_fetch_with_retry(start_time, end_time, attempt=0) → SourceResponse`

Implements retry logic with exponential backoff:

1. **Rate limit check** → `TokenBucket.wait_for_tokens()`
2. **Fetch** → calls `self.fetch()` (subclass)
3. **Permanent error?** → Fail immediately (HTTP 4xx except 429)
4. **Transient error?** → Retry with backoff
   - Timeout / Connection error: retry up to 3 times
   - HTTP 429/5xx: retried by HTTP adapter (built into Session)

**Retry delays:**
- Attempt 1: 2.0s ± 10% jitter
- Attempt 2: 4.0s ± 10% jitter
- Attempt 3: 8.0s ± 10% jitter

##### `_get_retry_delay(attempt) → float`

Calculates delay with exponential backoff + jitter:
```python
delay = config.retry.delays_seconds[attempt]
jitter = delay * config.retry.jitter_fraction  # ±10%
jittered_delay = delay + random.uniform(-jitter, jitter)
return max(0.1, jittered_delay)
```

#### Abstract Methods (Subclasses Must Implement)

##### `fetch(start_time, end_time) → SourceResponse`
Make actual API request to data source.

**Subclass example (OpenAQ):**
```python
def fetch(self, start_time, end_time):
    url = f"{self.config.base_url}/latest"
    params = {
        "bbox": "22.45,88.2,22.65,88.5",
        "limit": 10000,
        "sort": "desc",
        "date_from": start_time.isoformat()
    }
    response = self._session.get(url, params=params, timeout=self.config.timeout_seconds)
    return SourceResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        body=response.json(),
        elapsed_seconds=response.elapsed.total_seconds(),
        timestamp=datetime.now(timezone.utc)
    )
```

##### `parse(response, start_time, end_time) → List[ParsedRecord]`
Extract canonical records from API response.

**Subclass example:**
```python
def parse(self, response, start_time, end_time):
    records = []
    for obs in response.body.get("results", []):
        measurement_key = hashlib.sha256(
            f"{self.config.source_name}|{obs['station_id']}|{obs['pollutant']}|{obs['observed_at']}".encode()
        ).hexdigest()
        records.append(ParsedRecord(
            source="openaq",
            record_type="air_quality",
            data={
                "station_id": obs["station_id"],
                "pollutant": obs["pollutant"],
                "value": obs["value"],
                "unit": obs["unit"],
                "observed_at": obs["observed_at"]
            },
            measurement_key=measurement_key,
            raw_payload_hash=response.raw_payload_hash,
            ingestion_timestamp=datetime.now(timezone.utc)
        ))
    return records
```

##### `validate_source_response(response) → None`
Validate response format. Default implementation checks HTTP status.

##### `write_raw(records, run_id) → Tuple[int, int]`
Write parsed records to Parquet storage.

Returns: (records_written, records_rejected)

##### `record_run(metadata, success) → None`
Record ingestion run in PostgreSQL control plane.

**Important:** Never advance watermark if `success=False`.

#### Helper Methods

##### `_create_session() → requests.Session` (Static)
Create thread-safe session with built-in retry adapter:
- Retries: 3 total
- Status codes: [429, 500, 502, 503, 504]
- Backoff: exponential (1s, 2s, 4s)

##### `_get_cached_response(url) → Optional[SourceResponse]`
Retrieve cached response from dev cache directory.

##### `_cache_response(url, response) → None`
Cache response for development/testing.

---

## 3. Connector Package (__init__.py)

Exports all public APIs:
```python
from aq_engine.connectors import (
    BaseConnector,
    TokenBucket,
    ConnectorConfig,
    RetryConfig,
    RateLimitConfig,
    SourceResponse,
    ParsedRecord,
    Watermark,
    IngestionRunMetadata,
)
```

---

## Retry Policy

### Decision Tree

```
HTTP 2xx (success)
  → Proceed

HTTP 429 (Rate Limit)
  → Retry up to 3 times with backoff [2s, 4s, 8s]
  → Applies jitter (±10%) to prevent thundering herd

HTTP 5xx (Server Error)
  → Retry up to 3 times with backoff [2s, 4s, 8s]

Timeout / Connection Error
  → Retry up to 3 times with backoff [2s, 4s, 8s]

HTTP 4xx (except 429)
  → Fail immediately (permanent error)
  → Log and do NOT advance watermark

Malformed Payload / Parse Error
  → Fail immediately
  → Log error with context
  → Do NOT advance watermark
```

### Backoff Algorithm

```python
attempt = 0:  delay = 2.0s ± random(0, 0.2)s
attempt = 1:  delay = 4.0s ± random(0, 0.4)s
attempt = 2:  delay = 8.0s ± random(0, 0.8)s
```

Minimum delay: 0.1s (safety)
Maximum wait: 60s before giving up on rate limit

---

## Watermark Management

### Watermark Storage
Stored in PostgreSQL `ingestion_run` table:
- `last_successful_event_time`: Last observation timestamp successfully ingested
- `last_ingestion_time`: When last successful run completed
- `last_attempted_time`: When last attempt was made (even if failed)

### Watermark Update Policy

**If ingestion succeeds:**
```python
watermark.last_successful_event_time = max(observed_at for all records)
watermark.last_ingestion_time = now
```

**If ingestion fails:**
```python
watermark.last_attempted_time = now
# DO NOT UPDATE: last_successful_event_time or last_ingestion_time
```

### Incremental Query Window

```python
watermark = load_watermark(source_id)
if watermark.last_successful_event_time:
    query_start = watermark.last_successful_event_time
else:
    query_start = now - 6 hours  # Default lookback
query_end = now
```

---

## Thread Safety

All shared state is protected by locks:
- `TokenBucket`: `self._lock` guards token count
- `BaseConnector`: `self._lock` available for subclasses

Session reuse:
- `requests.Session` is thread-safe for concurrent GET requests
- Pass same session to multiple connector instances for connection pooling

---

## Testing & Development

### Response Caching (Optional)

```python
# Development: cache responses to avoid repeated API calls
connector = OpenAQConnector(
    config=config,
    response_cache_dir=Path("tests/fixtures/responses")
)

# First call hits API and caches response
response = connector.fetch(start, end)

# Second call uses cached response (via _get_cached_response)
response = connector.fetch(start, end)  # No API call
```

### Session Injection (for Testing)

```python
# Test: mock HTTP responses
mock_session = Mock(spec=requests.Session)
mock_session.get.return_value = Mock(
    status_code=200,
    json=lambda: {"results": [...]},
    elapsed=timedelta(seconds=0.5)
)

connector = OpenAQConnector(config, session=mock_session)
# connector.fetch() uses mock_session
```

---

## Usage Examples

### Basic Ingestion

```python
from aq_engine.connectors import BaseConnector, ConnectorConfig
from datetime import datetime, timezone

class OpenAQConnector(BaseConnector):
    def fetch(self, start_time, end_time):
        # API call here
        pass
    
    def parse(self, response, start_time, end_time):
        # Extract records
        pass
    
    def write_raw(self, records, run_id):
        # Write to Parquet
        pass
    
    def record_run(self, metadata, success):
        # Update PostgreSQL
        pass

# Ingest
config = ConnectorConfig(
    source_name="openaq",
    source_type="air_quality",
    base_url="https://api.openaq.org/v3",
    timeout_seconds=30
)

connector = OpenAQConnector(config)
run_id, metadata = connector.ingest()
print(f"Run {run_id}: {metadata.records_written} written, {metadata.records_rejected} rejected")
```

### With Watermark

```python
# Load watermark
watermark = load_watermark_from_db(source_id=1)

# Ingest with incremental window
run_id, metadata = connector.ingest(watermark=watermark)

# Watermark automatically updated if success
if metadata.status == "success":
    update_watermark_in_db(watermark)  # Caller's responsibility
else:
    logger.warning("Watermark not updated due to failure")
```

### With Custom Config

```python
config = ConnectorConfig(
    source_name="openaq",
    source_type="air_quality",
    base_url="https://api.openaq.org/v3",
    timeout_seconds=30,
    retry=RetryConfig(
        max_attempts=5,  # More retries
        delays_seconds=[1, 2, 4, 8, 16],
        jitter_fraction=0.2  # More jitter
    ),
    rate_limit=RateLimitConfig(
        requests_per_minute=100,
        max_parallel_requests=2
    )
)

connector = OpenAQConnector(config)
```

---

## Quality Standards Met

✅ **Type Hints**
- Full type hints throughout (no `Any` unless necessary)
- Generic typing for responses (Dict, List, Tuple)
- Dataclass validation in `__init__`

✅ **Error Handling**
- All exceptions caught and logged with context
- `IngestionFailed`, `DataContractViolation` raised appropriately
- Tracebacks logged for debugging

✅ **Configuration**
- No hardcoded delays, retry counts, or URLs
- All parameterized via `ConnectorConfig`
- Loaded from YAML configs (configs/sources/*.yaml)

✅ **Logging**
- All operations logged with context (source, run_id, records)
- Duration tracking
- Exception details in error logs
- `StructuredLogger` for domain events

✅ **Session Management**
- Thread-safe reuse via `requests.Session`
- Built-in HTTP retry adapter
- Connection pooling

✅ **Testability**
- Dependency injection for session (mock in tests)
- Abstract methods force clear contracts
- Response caching for deterministic testing

✅ **Documentation**
- Comprehensive docstrings with examples
- Retry policy documented
- Watermark semantics clear
- Usage examples provided

---

## Next Steps: M1 Ingestion Implementation

Concrete connectors will implement abstract methods:
- **OpenAQConnector**: Fetch from OpenAQ API, parse air quality observations
- **OpenMeteoConnector**: Fetch from Open-Meteo API, parse weather data

Both will:
- Load config from `configs/sources/*.yaml`
- Use retry/rate-limit logic from BaseConnector
- Write canonical records to Parquet
- Record runs in PostgreSQL
- Manage watermarks for incremental ingestion
