"""Ingestion orchestration logic.

Ties together connectors, quality validation, storage, and control plane.
Implements idempotency, watermark management, and comprehensive error handling.
"""

import gc
import logging
import yaml
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4

from aq_engine.common import (
    ensure_utc,
    get_date_range,
    log_operation,
    StructuredLogger,
    IngestionFailed,
    StorageError,
    DatabaseError,
)
from aq_engine.connectors.openaq import OpenAQConnector
from aq_engine.connectors.open_meteo import OpenMeteoConnector
from aq_engine.connectors.models import ConnectorConfig
from aq_engine.quality.contracts import RawAirQualityRecord, RawWeatherRecord
from aq_engine.quality.hashing import generate_measurement_key, generate_weather_key
from aq_engine.storage.parquet_io import ParquetWriter
from aq_engine.storage.db import Database, IngestionRunRepository, LocationRepository, StationRepository


logger = logging.getLogger(__name__)
slog = StructuredLogger(__name__)


class IngestionOrchestrator:
    """Orchestrates end-to-end ingestion workflow.

    Coordinates fetching, validation, deduplication, storage, and metadata tracking.
    Implements idempotency via measurement keys and watermark-based incremental ingestion.

    Example:
        >>> orchestrator = IngestionOrchestrator(
        ...     config_dir="configs",
        ...     storage_root="data/raw",
        ...     db_url="postgresql://localhost/aq_control"
        ... )
        >>> stats = orchestrator.ingest_source("openaq")
        >>> print(f"Ingested {stats['records_written']} records")
    """

    def __init__(
        self,
        config_dir: str = "configs",
        storage_root: str = "data/raw",
        db_url: str = "postgresql://localhost/aq_control",
    ):
        """Initialize orchestrator.

        Args:
            config_dir: Directory containing source configs.
            storage_root: Root directory for Parquet storage.
            db_url: PostgreSQL connection string.
        """
        self.config_dir = Path(config_dir)
        self.storage_root = storage_root

        # Initialize storage and database
        self.parquet_writer = ParquetWriter(root_path=storage_root)
        self.db = Database(db_url, echo=False)

        # Initialize repositories
        self.ingestion_repo = IngestionRunRepository(self.db)
        self.location_repo = LocationRepository(self.db)
        self.station_repo = StationRepository(self.db)

        logger.info(
            f"IngestionOrchestrator initialized: "
            f"config_dir={config_dir}, storage_root={storage_root}"
        )

    def ingest_source(
        self,
        source_name: str,
        lookback_hours: float = 6.0,
    ) -> Dict[str, Any]:
        """Ingest data from a source using watermark-based incremental logic.

        Implements complete workflow:
        1. Load connector config
        2. Get watermark from DB
        3. Fetch data from API
        4. Parse and validate
        5. Deduplicate
        6. Write to Parquet
        7. Record to PostgreSQL
        8. Advance watermark on success

        Args:
            source_name: Source identifier ("openaq", "open_meteo").
            lookback_hours: Lookback window if no watermark (default 6 hours).

        Returns:
            Dict with ingestion stats:
            - run_id: Ingestion run UUID
            - source_name: Source name
            - status: "success", "failed", or "partial"
            - records_received: Total fetched
            - records_written: Successfully written
            - records_rejected: Rejected (invalid)
            - duration_seconds: Total time
            - error_message: Error if failed (optional)

        Raises:
            IngestionFailed: On critical failures (API, DB write).
        """
        run_id = str(uuid4())
        started_at = datetime.now(timezone.utc)

        # Initialize stats
        stats = {
            "run_id": run_id,
            "source_name": source_name,
            "status": "running",
            "records_received": 0,
            "records_written": 0,
            "records_rejected": 0,
            "error_message": None,
        }

        with log_operation(
            f"ingest_{source_name}",
            {"run_id": run_id, "source": source_name},
        ):
            try:
                # Load config
                config = self._load_config(source_name)
                source_id = self._get_source_id(source_name)

                # Initialize connector
                connector = self._init_connector(source_name, config)

                # Get watermark
                watermark_end, _ = self.ingestion_repo.get_latest_watermark(source_id)
                if watermark_end:
                    query_start = watermark_end
                else:
                    query_start = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
                query_end = datetime.now(timezone.utc)

                logger.info(
                    f"Ingesting {source_name}: "
                    f"{query_start.isoformat()} to {query_end.isoformat()}"
                )

                # Fetch data
                response = connector.fetch(query_start, query_end)
                stats["records_received"] = response.body.get("meta", {}).get("total", 0)

                # Parse into canonical records
                parsed_records = connector.parse(response, query_start, query_end)

                # Validate and deduplicate
                deduplicated = self._deduplicate(source_name, parsed_records)
                stats["records_rejected"] = stats["records_received"] - len(deduplicated)

                # Write to Parquet
                if deduplicated:
                    partition_date = query_end.date()
                    self._write_records(source_name, deduplicated, partition_date)
                    stats["records_written"] = len(deduplicated)
                else:
                    logger.warning(f"No records to write for {source_name} after deduplication")

                # Record to PostgreSQL
                self.ingestion_repo.record_run(
                    run_id=run_id,
                    source_id=source_id,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    status="success",
                    records_received=stats["records_received"],
                    records_written=stats["records_written"],
                    records_rejected=stats["records_rejected"],
                    requested_start=query_start,
                    requested_end=query_end,
                )

                stats["status"] = "success"
                slog.ingestion_complete(
                    source_name,
                    records_received=stats["records_received"],
                    records_written=stats["records_written"],
                    records_rejected=stats["records_rejected"],
                )

            except IngestionFailed as e:
                stats["status"] = "failed"
                stats["error_message"] = str(e)

                # Record failed run (watermark NOT advanced)
                try:
                    self.ingestion_repo.record_run(
                        run_id=run_id,
                        source_id=self._get_source_id(source_name),
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        status="failed",
                        error_message=str(e),
                    )
                except DatabaseError as db_err:
                    logger.error(f"Failed to record ingestion failure: {db_err}")

                slog.ingestion_error(source_name, error=str(e))
                logger.error(f"Ingestion failed: {e}", exc_info=True)
                raise

            except Exception as e:
                stats["status"] = "failed"
                stats["error_message"] = str(e)

                slog.ingestion_error(source_name, error=str(e))
                logger.error(f"Unexpected error during ingestion: {e}", exc_info=True)
                raise IngestionFailed(
                    f"Ingestion failed: {str(e)}",
                    context={"source": source_name, "run_id": run_id},
                ) from e

            finally:
                # Add duration
                stats["duration_seconds"] = (datetime.now(timezone.utc) - started_at).total_seconds()

        return stats

def ingest_source_backfill(
    self,
    source_name: str,
    start_date: date,
    end_date: date,
) -> dict:
    """
    Backfill historical data one day at a time.

    Memory is bounded to the data required for a single day instead of
    loading the complete requested date range into memory.

    Each day follows this lifecycle:

        fetch -> parse -> deduplicate -> write -> release memory -> next day

    This prevents multi-month/year backfills from retaining the complete
    payload in memory and significantly reduces the risk of OOM/SIGKILL 137.
    """

    connector = self.connectors.get(source_name)

    if connector is None:
        raise ValueError(f"No connector configured for source: {source_name}")

    if start_date > end_date:
        raise ValueError(
            f"Invalid date range: {start_date} > {end_date}"
        )

    aggregate_stats = {
        "source": source_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_records_received": 0,
        "total_records_written": 0,
        "total_records_rejected": 0,
        "days_processed": 0,
        "days_failed": 0,
    }

    current_date = start_date

    while current_date <= end_date:

        # Keep the processing window strictly limited to one day.
        day_start = datetime.combine(
            current_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )

        day_end = datetime.combine(
            current_date,
            datetime.max.time(),
            tzinfo=timezone.utc,
        )

        # Explicitly initialize these references so that they can
        # always be released in the finally block.
        response = None
        parsed_records = None
        deduplicated = None

        try:
            logger.info(
                f"Starting backfill for {source_name} on {current_date}"
            )

            # ---------------------------------------------------------
            # 1. FETCH ONLY ONE DAY
            # ---------------------------------------------------------
            response = connector.fetch(
                day_start,
                day_end,
            )

            records_received = (
                response.body.get("meta", {}).get("total", 0)
            )

            # ---------------------------------------------------------
            # 2. PARSE ONLY THAT DAY
            # ---------------------------------------------------------
            parsed_records = connector.parse(
                response,
                day_start,
                day_end,
            )

            # ---------------------------------------------------------
            # 3. DEDUPLICATE ONLY THAT DAY
            # ---------------------------------------------------------
            deduplicated = self._deduplicate(
                source_name,
                parsed_records,
            )

            # ---------------------------------------------------------
            # 4. WRITE ONLY THAT DAY
            # ---------------------------------------------------------
            if deduplicated:
                self._write_records(
                    source_name,
                    deduplicated,
                    current_date,
                )

                records_written = len(deduplicated)
            else:
                records_written = 0

            # Do not allow a negative rejected count if the source
            # metadata is inconsistent.
            records_rejected = max(
                0,
                records_received - records_written,
            )

            aggregate_stats["total_records_received"] += (
                records_received
            )

            aggregate_stats["total_records_written"] += (
                records_written
            )

            aggregate_stats["total_records_rejected"] += (
                records_rejected
            )

            aggregate_stats["days_processed"] += 1

            logger.info(
                f"Backfill day {current_date} completed: "
                f"{records_written} written, "
                f"{records_rejected} rejected"
            )

        except Exception as exc:
            aggregate_stats["days_failed"] += 1

            logger.warning(
                f"Backfill failed for {source_name} "
                f"on {current_date}: {exc}",
                exc_info=True,
            )

        finally:
            # ---------------------------------------------------------
            # IMPORTANT:
            # Release all large per-day objects BEFORE moving to the
            # next date.
            # ---------------------------------------------------------
            response = None
            parsed_records = None
            deduplicated = None

            gc.collect()

        # Move to the next day only after the previous day's objects
        # have been released.
        current_date += timedelta(days=1)

    logger.info(
        f"Backfill completed for {source_name}: "
        f"{aggregate_stats}"
    )

    return aggregate_stats

    def _load_config(self, source_name: str) -> Dict[str, Any]:
        """Load connector configuration from YAML.

        Args:
            source_name: Source identifier.

        Returns:
            Configuration dict.

        Raises:
            IngestionFailed: If config not found or invalid.
        """
        config_path = self.config_dir / "sources" / f"{source_name}.yaml"

        if not config_path.exists():
            raise IngestionFailed(
                f"Config not found for {source_name}",
                context={"config_path": str(config_path)},
            )

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            logger.debug(f"Loaded config for {source_name}")
            return config
        except Exception as e:
            raise IngestionFailed(
                f"Failed to load config for {source_name}: {str(e)}",
                context={"config_path": str(config_path)},
            ) from e

    def _get_source_id(self, source_name: str) -> int:
        """Get or create source in database.

        Args:
            source_name: Source identifier.

        Returns:
            Source ID.

        Raises:
            DatabaseError: On database error.
        """
        # TODO: Implement after source repository is created
        # For now, return hardcoded IDs for testing
        source_ids = {"openaq": 1, "open_meteo": 2}
        return source_ids.get(source_name, 0)

    def _init_connector(self, source_name: str, config: Dict[str, Any]):
        """Initialize connector instance.

        Args:
            source_name: Source identifier.
            config: Source configuration.

        Returns:
            Initialized connector.

        Raises:
            IngestionFailed: If connector creation fails.
        """
        try:
            if source_name == "openaq":
                connector_config = ConnectorConfig(
                    source_name="openaq",
                    source_type="air_quality",
                    base_url=config["openaq"]["base_url"],
                    timeout_seconds=config["openaq"].get("timeout_seconds", 30),
                )
                return OpenAQConnector(connector_config)

            elif source_name == "open_meteo":
                connector_config = ConnectorConfig(
                    source_name="open_meteo",
                    source_type="weather",
                    base_url=config["open_meteo"]["base_url"],
                    timeout_seconds=config["open_meteo"].get("timeout_seconds", 30),
                )
                connector = OpenMeteoConnector(connector_config)
                # TODO: Add location mappings from database
                return connector

            else:
                raise IngestionFailed(
                    f"Unknown source: {source_name}",
                    context={"source": source_name},
                )

        except Exception as e:
            raise IngestionFailed(
                f"Failed to initialize connector: {str(e)}",
                context={"source": source_name},
            ) from e

    def _deduplicate(self, source_name: str, records: List[Dict]) -> List[Dict]:
        """Deduplicate records using measurement keys.

        Reads existing Parquet data for current date, checks for duplicates.

        Args:
            source_name: Source identifier.
            records: Parsed records.

        Returns:
            Deduplicated records.
        """
        if not records:
            return records

        # Generate measurement keys
        keys_to_records = {}
        for record in records:
            if source_name == "openaq":
                key = generate_measurement_key(
                    source=record["source"],
                    station_id=record["station_id"],
                    sensor_id=record["sensor_id"],
                    pollutant=record["pollutant"],
                    observed_at=record["observed_at"],
                )
            else:  # open_meteo
                key = generate_weather_key(
                    source=record["source"],
                    location_id=record["location_id"],
                    observed_at=record["observed_at"],
                )

            keys_to_records[key] = record

        # TODO: Check Parquet for existing keys
        # For now, just deduplicate within this batch
        deduplicated = list(keys_to_records.values())

        if len(deduplicated) < len(records):
            logger.info(
                f"Deduplication removed {len(records) - len(deduplicated)} "
                f"duplicate records"
            )

        return deduplicated

    def _write_records(
        self,
        source_name: str,
        records: List[Dict],
        partition_date: date,
    ) -> None:
        """Write records to Parquet storage.

        Args:
            source_name: Source identifier.
            records: Canonical records.
            partition_date: Partition date.

        Raises:
            StorageError: On write failure.
        """
        try:
            if source_name == "openaq":
                self.parquet_writer.write_air_quality_raw(records, partition_date)
            else:  # open_meteo
                self.parquet_writer.write_weather_raw(records, partition_date)

            logger.info(f"Wrote {len(records)} records to Parquet for {partition_date}")

        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"Failed to write records to Parquet: {str(e)}",
                context={"source": source_name, "partition_date": str(partition_date)},
            ) from e
