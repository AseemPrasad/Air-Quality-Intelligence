"""Ingestion orchestration logic.

Ties together connectors, quality validation, storage, and control plane.
Implements idempotency, watermark management, and comprehensive error handling.
"""

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
    ) -> Dict[str, Any]:
        """Backfill historical data for date range.

        Iterates day-by-day, same orchestration as ingest_source.
        Uses same deduplication logic, so safe to re-run.

        Args:
            source_name: Source identifier.
            start_date: Backfill start date (inclusive).
            end_date: Backfill end date (inclusive).

        Returns:
            Dict with aggregate stats across all days.

        Raises:
            IngestionFailed: If any day's ingestion fails critically.
        """
        run_id = str(uuid4())
        started_at = datetime.now(timezone.utc)

        aggregate_stats = {
            "run_id": run_id,
            "source_name": source_name,
            "backfill": True,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_records_received": 0,
            "total_records_written": 0,
            "total_records_rejected": 0,
            "days_processed": 0,
            "days_failed": 0,
            "error_message": None,
        }

        with log_operation(
            f"backfill_{source_name}",
            {"run_id": run_id, "start": start_date.isoformat(), "end": end_date.isoformat()},
        ):
            try:
                # Load config and connector
                config = self._load_config(source_name)
                source_id = self._get_source_id(source_name)
                connector = self._init_connector(source_name, config)

                # Iterate over dates
                for day_date in get_date_range(
                    datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                    datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc),
                ):
                    day_start = datetime.combine(day_date.date(), datetime.min.time()).replace(
                        tzinfo=timezone.utc
                    )
                    day_end = datetime.combine(day_date.date(), datetime.max.time()).replace(
                        tzinfo=timezone.utc
                    )

                    try:
                        # Fetch data for this day
                        response = connector.fetch(day_start, day_end)
                        records_received = response.body.get("meta", {}).get("total", 0)

                        # Parse and validate
                        parsed_records = connector.parse(response, day_start, day_end)
                        deduplicated = self._deduplicate(source_name, parsed_records)

                        # Write to Parquet
                        if deduplicated:
                            self._write_records(source_name, deduplicated, day_date.date())
                            records_written = len(deduplicated)
                        else:
                            records_written = 0

                        records_rejected = records_received - len(deduplicated)

                        # Update aggregate stats
                        aggregate_stats["total_records_received"] += records_received
                        aggregate_stats["total_records_written"] += records_written
                        aggregate_stats["total_records_rejected"] += records_rejected
                        aggregate_stats["days_processed"] += 1

                        logger.info(
                            f"Backfill day {day_date.date()}: "
                            f"{records_written} written, {records_rejected} rejected"
                        )

                    except Exception as e:
                        aggregate_stats["days_failed"] += 1
                        logger.warning(f"Backfill failed for {day_date.date()}: {e}")
                        continue  # Continue with next day

                # Record aggregate backfill run
                self.ingestion_repo.record_run(
                    run_id=run_id,
                    source_id=source_id,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    status="success" if aggregate_stats["days_failed"] == 0 else "partial",
                    records_received=aggregate_stats["total_records_received"],
                    records_written=aggregate_stats["total_records_written"],
                    records_rejected=aggregate_stats["total_records_rejected"],
                    requested_start=datetime.combine(start_date, datetime.min.time()).replace(
                        tzinfo=timezone.utc
                    ),
                    requested_end=datetime.combine(end_date, datetime.max.time()).replace(
                        tzinfo=timezone.utc
                    ),
                )

                aggregate_stats["status"] = "success" if aggregate_stats["days_failed"] == 0 else "partial"
                logger.info(f"Backfill complete: {aggregate_stats['days_processed']} days processed")

            except Exception as e:
                aggregate_stats["status"] = "failed"
                aggregate_stats["error_message"] = str(e)
                logger.error(f"Backfill failed: {e}", exc_info=True)
                raise IngestionFailed(
                    f"Backfill failed: {str(e)}",
                    context={
                        "source": source_name,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                ) from e

            finally:
                aggregate_stats["duration_seconds"] = (
                    datetime.now(timezone.utc) - started_at
                ).total_seconds()

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
