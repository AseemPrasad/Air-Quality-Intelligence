# Configuration & Logging Layer - Deliverables Summary

## ✓ COMPLETE (8 Files)

### YAML Configuration Files (4)

#### 1. **configs/base.yaml** (2.4K)
- Platform metadata (name, version, environment)
- Data retention & partitioning settings
- Quality validation thresholds:
  - Humidity: 0–100%, Wind direction: 0–360°, Future tolerance: 1h
  - Flatline detection: 5 consecutive identical values
- Anomaly scoring thresholds:
  - Normal: <2.0, Elevated: 2.0, High: 3.0, Severe: 4.0, Extreme: 5.0
- Pollution event detection criteria:
  - Min 3 consecutive high hours OR 3 in 4-hour window
  - Merge events separated by ≤1 hour
- ML model promotion threshold: 5% MAE improvement
- Default forecast horizons: [1h, 3h, 6h]
- Storage paths & Parquet configuration (compression: snappy)

#### 2. **configs/logging.yaml** (2.8K)
Python `logging.config.dictConfig` format with:
- **3 Formatters:**
  - `json`: Structured JSON (pythonjsonlogger.JsonFormatter)
  - `standard`: Text format for development
  - `detailed`: Text with file/line context

- **5 Handlers:**
  - `console`: JSON to stdout (INFO level)
  - `file`: Rotating log to logs/aq_engine.log (10MB/file, 5 rotations)
  - `error_file`: Separate error log (ERROR level)
  - `ingestion_file`: Ingestion operations
  - `ml_file`: ML operations

- **9 Module-Specific Loggers:**
  - `aq_engine`: root (DEBUG)
  - `aq_engine.connectors`: ingestion (DEBUG)
  - `aq_engine.quality`: validation (DEBUG)
  - `aq_engine.analytics`: analytics (DEBUG)
  - `aq_engine.ml`: ML pipeline (DEBUG)
  - `aq_engine.api`: API (INFO)
  - `aq_engine.dashboard`: Dashboard (INFO)
  - Third-party (airflow, sqlalchemy, polars): WARNING

#### 3. **configs/sources/openaq.yaml** (1.4K)
OpenAQ API configuration:
- Base URL: https://api.openaq.org/v3
- Timeout: 30s
- Rate limit: 60 req/min
- Retry: 3 attempts with [2s, 4s, 8s] exponential backoff
- Transient codes: [429, 500, 502, 503, 504]
- Kolkata bounds: 22.45–22.65°N, 88.2–88.5°E
- Pollutants: PM2.5 (priority 1), PM10, NO2, O3, SO2
- Data: Real-time + 7 years historical

#### 4. **configs/sources/open_meteo.yaml** (2.1K)
Open-Meteo API configuration:
- Base URL: https://api.open-meteo.com/v1
- Timeout: 30s
- Rate limit: 60 req/min, max 2 parallel
- No API key required (free service)
- Retry: 3 attempts with [2s, 4s, 8s] backoff
- Weather parameters:
  - Temperature (2m), Relative Humidity (2m)
  - Wind Speed/Direction (10m)
  - Pressure (MSL), Precipitation, Cloud Cover
- Data: Real-time + 10k day historical + 16-day forecast

### Python Modules (4)

#### 5. **src/aq_engine/common/logger.py** (11K)
Structured logging with context tracking:

**Functions:**
- `load_logging_config(config_path)` — Load dictConfig from YAML
- `get_logger(name)` — Get named logger with lazy initialization
- `log_operation(name, context, logger)` — Context manager for operation tracking
  - Logs start, completion (with duration), or failure (with traceback)

**Classes:**
- `StructuredLogger` — Domain-specific logging methods:
  - `ingestion_start()`, `ingestion_complete()`, `ingestion_error()`
  - `quality_check(passed, suspicious, invalid)`
  - `anomaly_detected(location_id, pollutant, value, z_score, severity)`
  - `event_detected(location_id, pollutant, start_time, duration, peak)`
  - `model_training_start()`, `model_training_complete()`
  - `model_promotion(from_version, to_version)`
  - `prediction_generated(location_id, horizon, value)`

**Features:**
- Lazy initialization (auto-defaults if no config loaded)
- JSON structured logging (pythonjsonlogger)
- Exception context preservation
- Duration tracking for operations
- Module-level handlers (ingestion.log, ml.log separate from main)

#### 6. **src/aq_engine/common/time.py** (9.2K)
Timezone-aware datetime utilities:

**Core Functions:**
- `ensure_utc(dt)` — Convert to UTC, validate bounds (±200 years)
- `to_ist(dt)` — Convert to Asia/Kolkata timezone
- `round_to_hour(dt, direction="floor"|"ceil")` — Round to hour boundary
- `is_future(dt, tolerance_hours=0)` — Check if date is in future

**Partitioning:**
- `date_partition_path(dt)` → "year=2026/month=08/day=15"
- `hour_partition_path(dt)` → "year=2026/month=08/day=15/hour=12"

**Iteration:**
- `get_date_range(start, end)` — List of midnights for each day
- `get_hour_range(start, end)` — List of hourly boundaries

**Parsing & Formatting:**
- `timestamp_iso8601(dt)` → ISO 8601 with timezone
- `parse_iso8601(timestamp)` — Parse multiple ISO formats
- `days_ago(days)` → Midnight UTC N days ago
- `hours_ago(hours)` → N hours ago

**Features:**
- UTC-first design (all output in UTC)
- DST-safe (using pytz for conversions)
- Handles naive and timezone-aware datetimes
- Comprehensive edge-case handling
- Full type hints

#### 7. **src/aq_engine/common/exceptions.py** (6.8K)
Custom exceptions with context tracking:

**Exception Hierarchy:**
- `AQEngineException` (base) — attributes: message, context (dict), cause
  - `DataContractViolation` — Missing/invalid fields, type mismatches
  - `QualityCheckFailed` — Semantic, structural, referential, temporal violations
  - `IngestionFailed` — HTTP errors, timeouts, malformed responses
  - `DuplicateRecordError` — Duplicate observations
  - `AnomalyDetectionError` — Insufficient data, computation errors
  - `EventDetectionError` — Time series validation, merging errors
  - `MLPromotionFailed` — Performance threshold not met
  - `MLTrainingFailed` — Training data/hyperparameter errors
  - `PredictionFailed` — Model/feature/inference errors
  - `StorageError` — Parquet I/O, disk errors
  - `ConfigurationError` — Config file/syntax errors
  - `DatabaseError` — Connection, query, schema errors
  - `ValidationError` — Business logic validation failures

**Features:**
- Fluent context builder: `exc.add_context(key, value)` chaining
- Exception chaining: `cause` parameter preserves original exception
- Detailed `__str__` with context and cause
- `handle_exception(exc, context)` wrapper for library exceptions
- Full type hints

#### 8. **src/aq_engine/common/__init__.py** (1.7K)
Package exports:
- All public APIs from logger, time, exceptions
- Single import point: `from aq_engine.common import *`

## Quality Standards Met

### YAML Configuration
- ✅ Valid YAML syntax (testable)
- ✅ Comprehensive comments and structure
- ✅ All thresholds documented
- ✅ Geographic bounds for Kolkata explicit
- ✅ Retry/timeout configuration granular

### Logger Module
- ✅ Lazy initialization (sensible defaults)
- ✅ Structured JSON output (pythonjsonlogger)
- ✅ Context tracking (operation name, metadata)
- ✅ Duration measurement (start → completion)
- ✅ Exception chaining (cause preserved)
- ✅ Domain-specific events (StructuredLogger)
- ✅ Module-level handlers (ingestion/ML separate)
- ✅ Full type hints

### Time Utilities
- ✅ UTC-first design (always returns UTC)
- ✅ Timezone awareness (naive → UTC, aware → convert)
- ✅ DST-safe (pytz for conversions)
- ✅ Edge cases handled (future tolerance, rounding, bounds validation)
- ✅ Partition paths (Parquet-ready)
- ✅ Date/hour iteration
- ✅ ISO 8601 parsing (flexible)
- ✅ Full type hints with docstrings

### Exceptions
- ✅ Base class with context dict
- ✅ 12 specific exception types for different failures
- ✅ Exception chaining (cause preserved)
- ✅ Fluent context builder
- ✅ Domain-specific names (DataContractViolation, QualityCheckFailed, etc.)
- ✅ Traceable `__str__` override
- ✅ Library exception wrapper
- ✅ Full type hints

## Usage Examples

```python
from aq_engine.common import (
    load_logging_config,
    get_logger,
    log_operation,
    StructuredLogger,
    ensure_utc,
    round_to_hour,
    date_partition_path,
    is_future,
    IngestionFailed,
    QualityCheckFailed,
)
from datetime import datetime, timezone

# Initialize logging
load_logging_config("configs/logging.yaml")

# Use log_operation context manager
with log_operation("ingest_openaq", {"source": "openaq", "city": "Kolkata"}):
    logger = get_logger("aq_engine.connectors.openaq")
    logger.info("Fetching data from API")
    # Automatically logs start, completion with duration, or failure

# Structured logger for domain events
slog = StructuredLogger("aq_engine.ml")
slog.model_training_start("RandomForest", "pm25_1h", 10000)
slog.model_training_complete("RandomForest", mae=15.3, rmse=22.1, version="v1.0")

# Time utilities
now = datetime.now(timezone.utc)
hour_start = round_to_hour(now, "floor")           # Midnight of hour
partition = date_partition_path(now)               # "year=2026/month=08/day=16"
is_future_date = is_future(now, tolerance_hours=1) # Allow 1h clock skew

# Exception handling with context
try:
    fetch_data()
except Exception as e:
    raise IngestionFailed(
        "Failed to fetch OpenAQ data",
        context={"source": "openaq", "city": "Kolkata"}
    ).add_context("retry_count", 3) from e
```

## Next Steps

M1 Ingestion will use these configs and utilities:
- Load configs with `load_logging_config()` and `yaml.load()`
- Log ingestion progress with `log_operation()` and `StructuredLogger`
- Use time utilities for partition paths and late-arrival windows
- Raise domain-specific exceptions (IngestionFailed, DataContractViolation)
