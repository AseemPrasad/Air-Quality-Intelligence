"""Common utilities for the Air Quality Intelligence Platform.

Provides:
- logger: Structured logging with context tracking
- time: Timezone-aware datetime utilities
- exceptions: Custom exceptions with context support
"""

from aq_engine.common.logger import get_logger, load_logging_config, log_operation, StructuredLogger
from aq_engine.common.time import (
    ensure_utc,
    to_ist,
    round_to_hour,
    is_future,
    date_partition_path,
    hour_partition_path,
    get_date_range,
    get_hour_range,
    timestamp_iso8601,
    parse_iso8601,
    days_ago,
    hours_ago,
)
from aq_engine.common.exceptions import (
    AQEngineException,
    DataContractViolation,
    QualityCheckFailed,
    IngestionFailed,
    DuplicateRecordError,
    AnomalyDetectionError,
    EventDetectionError,
    MLPromotionFailed,
    MLTrainingFailed,
    PredictionFailed,
    StorageError,
    ConfigurationError,
    DatabaseError,
    ValidationError,
    handle_exception,
)

__all__ = [
    "get_logger",
    "load_logging_config",
    "log_operation",
    "StructuredLogger",
    "ensure_utc",
    "to_ist",
    "round_to_hour",
    "is_future",
    "date_partition_path",
    "hour_partition_path",
    "get_date_range",
    "get_hour_range",
    "timestamp_iso8601",
    "parse_iso8601",
    "days_ago",
    "hours_ago",
    "AQEngineException",
    "DataContractViolation",
    "QualityCheckFailed",
    "IngestionFailed",
    "DuplicateRecordError",
    "AnomalyDetectionError",
    "EventDetectionError",
    "MLPromotionFailed",
    "MLTrainingFailed",
    "PredictionFailed",
    "StorageError",
    "ConfigurationError",
    "DatabaseError",
    "ValidationError",
    "handle_exception",
]
