"""Custom exceptions for the Air Quality Intelligence Platform.

All exceptions are traceable with optional context dictionaries for including
operation-specific metadata (location_id, source, error_code, etc.).
"""

from typing import Any, Dict, Optional


class AQEngineException(Exception):
    """Base exception for all Air Quality Intelligence Platform errors.

    Provides consistent error context and traceability. Includes optional context
    dictionary for operation-specific metadata.

    Attributes:
        message: Human-readable error message.
        context: Optional dictionary with operation context (location_id, source, etc.).
        cause: Optional original exception (useful for exception chaining).
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        """Initialize AQEngineException.

        Args:
            message: Error description.
            context: Optional dictionary with operation context.
            cause: Optional original exception for chaining.
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.cause = cause

    def __str__(self) -> str:
        """Return detailed string representation including context."""
        msg = f"{self.__class__.__name__}: {self.message}"
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            msg += f" | context: {context_str}"
        if self.cause:
            msg += f" | caused by: {self.cause}"
        return msg

    def add_context(self, key: str, value: Any) -> "AQEngineException":
        """Add or update context field and return self for chaining.

        Args:
            key: Context key.
            value: Context value.

        Returns:
            Self for method chaining.

        Example:
            >>> exc = IngestionFailed("Failed to fetch data").add_context("source", "openaq")
        """
        self.context[key] = value
        return self


class DataContractViolation(AQEngineException):
    """Raised when ingested data violates canonical data contract.

    Examples:
    - Missing required fields (source, station_id, observed_at, value)
    - Field type mismatch (observed_at is not a timestamp)
    - Invalid observation timestamp (future date beyond tolerance)
    - Inconsistent payload structure
    """

    pass


class QualityCheckFailed(AQEngineException):
    """Raised when data quality validation fails and records must be quarantined.

    Examples:
    - Semantic violation: negative pollution concentration
    - Structural violation: humidity > 100%
    - Referential violation: unknown station_id
    - Temporal violation: observation older than retention window
    """

    pass


class IngestionFailed(AQEngineException):
    """Raised when ingestion from external data source fails.

    Examples:
    - HTTP error (401, 403, 500, 503)
    - Timeout after retries exhausted
    - Malformed API response
    - Network connectivity issue
    - Rate limit exceeded with backoff exhausted
    """

    pass


class DuplicateRecordError(AQEngineException):
    """Raised when a duplicate observation is detected during deduplication.

    Example:
        >>> exc = DuplicateRecordError(
        ...     "Duplicate observation",
        ...     context={"measurement_key": "abc123", "first_seen": "2026-08-15T10:00:00Z"}
        ... )
    """

    pass


class AnomalyDetectionError(AQEngineException):
    """Raised when anomaly detection computation fails.

    Examples:
    - Insufficient historical data to compute baseline
    - All historical values are NaN or missing
    - Statistical computation error (MAD calculation failed)
    """

    pass


class EventDetectionError(AQEngineException):
    """Raised when pollution event detection fails.

    Examples:
    - Time series validation error
    - Event merging logic error
    - Insufficient anomaly scores
    """

    pass


class MLPromotionFailed(AQEngineException):
    """Raised when model promotion to production fails.

    Examples:
    - Candidate model did not meet performance threshold
    - Candidate model failed validation test suite
    - Model artifact missing or corrupted
    - Model version conflict in registry
    """

    pass


class MLTrainingFailed(AQEngineException):
    """Raised when model training fails.

    Examples:
    - Insufficient training data
    - Feature generation error
    - Hyperparameter tuning failure
    - Model serialization error
    """

    pass


class PredictionFailed(AQEngineException):
    """Raised when prediction generation fails.

    Examples:
    - Required model not found in registry
    - Feature vector construction error
    - Model inference error
    - Prediction interval calculation failed
    """

    pass


class StorageError(AQEngineException):
    """Raised when data storage/retrieval operations fail.

    Examples:
    - Parquet write error (disk full, permission denied)
    - Parquet read error (corrupted file, schema mismatch)
    - Partition path creation failed
    - Volume mount not available
    """

    pass


class ConfigurationError(AQEngineException):
    """Raised when configuration is invalid or missing.

    Examples:
    - Configuration file not found
    - Invalid YAML/JSON syntax
    - Required config key missing
    - Invalid configuration value (out of bounds)
    """

    pass


class DatabaseError(AQEngineException):
    """Raised when database operations fail.

    Examples:
    - Connection error (PostgreSQL unavailable)
    - Query execution error
    - Transaction rollback required
    - Schema initialization failed
    """

    pass


class ValidationError(AQEngineException):
    """Raised when business logic validation fails.

    Examples:
    - Time series validation error (non-monotonic timestamps)
    - Data range validation (value outside expected bounds)
    - Consistency validation (conflicting observations)
    """

    pass


def handle_exception(exc: Exception, context: Optional[Dict[str, Any]] = None) -> AQEngineException:
    """Convert any exception to AQEngineException with context.

    Useful for wrapping library exceptions to maintain consistent error handling.

    Args:
        exc: Original exception.
        context: Optional context dictionary.

    Returns:
        AQEngineException with original exception as cause.

    Example:
        >>> try:
        ...     requests.get("https://invalid.url")
        ... except Exception as e:
        ...     wrapped = handle_exception(e, context={"source": "openaq"})
        ...     raise wrapped
    """
    if isinstance(exc, AQEngineException):
        return exc

    error_msg = f"{exc.__class__.__name__}: {str(exc)}"
    return AQEngineException(error_msg, context=context or {}, cause=exc)
