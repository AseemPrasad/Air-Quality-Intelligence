"""Structured logging configuration and utilities for the Air Quality Intelligence Platform."""

import logging
import logging.config
import contextlib
from pathlib import Path
from typing import Any, Dict, Optional
import json


_logger_initialized = False
_root_logger: Optional[logging.Logger] = None


def load_logging_config(config_path: str | Path) -> None:
    """Load logging configuration from YAML file using dictConfig.

    Args:
        config_path: Path to logging.yaml configuration file.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If config file is invalid.
    """
    global _logger_initialized, _root_logger

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Logging config not found: {config_path}")

    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Ensure logs directory exists
        Path("logs").mkdir(exist_ok=True)

        logging.config.dictConfig(config)
        _logger_initialized = True
        _root_logger = logging.getLogger("aq_engine")
        _root_logger.info("Logging configured from %s", config_path)

    except Exception as e:
        raise ValueError(f"Failed to load logging config from {config_path}: {e}") from e


def get_logger(name: str) -> logging.Logger:
    """Get a named logger instance.

    Initializes logging if not already done. Uses a reasonable default
    configuration if no explicit config has been loaded.

    Args:
        name: Logger name (typically __name__ or module path).

    Returns:
        Configured logger instance.
    """
    global _logger_initialized, _root_logger

    if not _logger_initialized:
        # Initialize with basic configuration if no config file provided
        _initialize_default_logging()

    return logging.getLogger(name)


def _initialize_default_logging() -> None:
    """Initialize logging with a sensible default configuration."""
    global _logger_initialized, _root_logger

    # Create logs directory
    Path("logs").mkdir(exist_ok=True)

    # Configure basic logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/aq_engine.log"),
        ],
    )

    _logger_initialized = True
    _root_logger = logging.getLogger("aq_engine")
    _root_logger.info("Logging initialized with default configuration")


@contextlib.contextmanager
def log_operation(
    operation_name: str,
    context: Optional[Dict[str, Any]] = None,
    logger: Optional[logging.Logger] = None,
):
    """Context manager for tracking named operations with structured logging.

    Logs operation start, successful completion, and any exceptions with
    duration and context. Useful for tracking ingestion, transformation,
    and ML pipeline stages.

    Args:
        operation_name: Human-readable operation name (e.g., "ingest_openaq").
        context: Optional dictionary of context data to include in logs.
        logger: Optional logger instance; uses default if not provided.

    Yields:
        None

    Example:
        >>> with log_operation("ingest_openaq", {"source": "openaq", "city": "Kolkata"}):
        ...     # Ingestion code here
        ...     pass
    """
    import time

    if logger is None:
        logger = get_logger(__name__)

    context = context or {}
    start_time = time.time()

    # Log operation start
    logger.info(
        f"Starting {operation_name}",
        extra={
            "operation": operation_name,
            "context": context,
            "event": "operation_start",
        },
    )

    try:
        yield
        # Log successful completion
        duration = time.time() - start_time
        logger.info(
            f"Completed {operation_name}",
            extra={
                "operation": operation_name,
                "context": context,
                "event": "operation_complete",
                "duration_seconds": duration,
            },
        )

    except Exception as e:
        # Log failure with exception details
        duration = time.time() - start_time
        logger.error(
            f"Failed {operation_name}: {str(e)}",
            extra={
                "operation": operation_name,
                "context": context,
                "event": "operation_failed",
                "duration_seconds": duration,
                "exception": str(e),
                "exception_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise


class StructuredLogger:
    """Wrapper around standard logger for structured logging with consistent schema.

    Provides convenience methods for common operations: ingestion, validation,
    transformation, ML operations, etc. Each method logs structured data suitable
    for downstream analysis.
    """

    def __init__(self, name: str):
        """Initialize a structured logger.

        Args:
            name: Logger name (typically module name).
        """
        self._logger = get_logger(name)

    def ingestion_start(self, source: str, requested_start: str, requested_end: str) -> None:
        """Log ingestion operation start."""
        self._logger.info(
            f"Ingestion started from {source}",
            extra={
                "event": "ingestion_start",
                "source": source,
                "requested_start": requested_start,
                "requested_end": requested_end,
            },
        )

    def ingestion_complete(
        self, source: str, records_received: int, records_written: int, records_rejected: int
    ) -> None:
        """Log ingestion operation completion."""
        self._logger.info(
            f"Ingestion completed from {source}",
            extra={
                "event": "ingestion_complete",
                "source": source,
                "records_received": records_received,
                "records_written": records_written,
                "records_rejected": records_rejected,
            },
        )

    def ingestion_error(self, source: str, error: str, retry_count: int = 0) -> None:
        """Log ingestion error with retry information."""
        self._logger.error(
            f"Ingestion error from {source}: {error}",
            extra={
                "event": "ingestion_error",
                "source": source,
                "error": error,
                "retry_count": retry_count,
            },
        )

    def quality_check(self, passed: int, suspicious: int, invalid: int) -> None:
        """Log quality check results."""
        self._logger.info(
            f"Quality check: {passed} valid, {suspicious} suspicious, {invalid} invalid",
            extra={
                "event": "quality_check",
                "passed": passed,
                "suspicious": suspicious,
                "invalid": invalid,
            },
        )

    def anomaly_detected(
        self,
        location_id: int,
        pollutant: str,
        value: float,
        anomaly_score: float,
        severity: str,
    ) -> None:
        """Log anomaly detection."""
        self._logger.warning(
            f"Anomaly detected: {location_id}/{pollutant} = {value} (z={anomaly_score}, {severity})",
            extra={
                "event": "anomaly_detected",
                "location_id": location_id,
                "pollutant": pollutant,
                "value": value,
                "anomaly_score": anomaly_score,
                "severity": severity,
            },
        )

    def event_detected(
        self,
        location_id: int,
        pollutant: str,
        start_time: str,
        duration_hours: int,
        peak_value: float,
    ) -> None:
        """Log pollution event detection."""
        self._logger.warning(
            f"Pollution event: {location_id}/{pollutant} starting {start_time} ({duration_hours}h)",
            extra={
                "event": "pollution_event_detected",
                "location_id": location_id,
                "pollutant": pollutant,
                "start_time": start_time,
                "duration_hours": duration_hours,
                "peak_value": peak_value,
            },
        )

    def model_training_start(self, model_name: str, target: str, training_records: int) -> None:
        """Log ML model training start."""
        self._logger.info(
            f"Training {model_name} for {target}",
            extra={
                "event": "model_training_start",
                "model_name": model_name,
                "target": target,
                "training_records": training_records,
            },
        )

    def model_training_complete(
        self, model_name: str, mae: float, rmse: float, version: str
    ) -> None:
        """Log ML model training completion."""
        self._logger.info(
            f"Training complete: {model_name} v{version} (MAE={mae:.4f})",
            extra={
                "event": "model_training_complete",
                "model_name": model_name,
                "mae": mae,
                "rmse": rmse,
                "version": version,
            },
        )

    def model_promotion(self, model_name: str, from_version: str, to_version: str) -> None:
        """Log model promotion to production."""
        self._logger.info(
            f"Promoted {model_name} from {from_version} to {to_version}",
            extra={
                "event": "model_promotion",
                "model_name": model_name,
                "from_version": from_version,
                "to_version": to_version,
            },
        )

    def prediction_generated(
        self, location_id: int, horizon_minutes: int, predicted_value: float
    ) -> None:
        """Log prediction generation."""
        self._logger.debug(
            f"Prediction for location {location_id} (+{horizon_minutes}min): {predicted_value}",
            extra={
                "event": "prediction_generated",
                "location_id": location_id,
                "horizon_minutes": horizon_minutes,
                "predicted_value": predicted_value,
            },
        )
