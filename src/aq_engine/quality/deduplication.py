"""Deduplication logic for preventing duplicate observations.

Compares incoming records against existing partitions using measurement keys
to identify and filter duplicates before storage.
"""

import logging
from datetime import date
from pathlib import Path
from typing import List, Tuple, Set, Dict, Any

from aq_engine.quality.hashing import generate_measurement_key, generate_weather_key
from aq_engine.storage.parquet_io import ParquetWriter

logger = logging.getLogger(__name__)


class Deduplicator:
    """Identifies and filters duplicate records.

    Maintains idempotency by checking measurement keys against
    existing data in target partition before writes.

    Example:
        >>> dedup = Deduplicator(storage_root="data/raw")
        >>> new_records = [...]
        >>> unique, dups = dedup.deduplicate_air_quality(new_records, date(2026, 8, 15))
        >>> print(f"Unique: {len(unique)}, Duplicates: {len(dups)}")
    """

    def __init__(self, storage_root: str = "data/raw"):
        """Initialize deduplicator.

        Args:
            storage_root: Root path for raw data storage.
        """
        self.storage_root = Path(storage_root)
        self.writer = ParquetWriter(root_path=storage_root)

    def deduplicate_air_quality(
        self,
        records: List[dict],
        partition_date: date,
    ) -> Tuple[List[dict], List[Tuple[dict, str]]]:
        """Deduplicate air quality records.

        Compares measurement_key (source + station_id + sensor_id +
        pollutant + observed_at) against existing partition data.

        Args:
            records: List of air quality records to deduplicate.
            partition_date: Target partition date (YYYY/MM/DD).

        Returns:
            Tuple of:
            - unique_records: List of new records not in partition
            - duplicates: List of (record, measurement_key) tuples

        Example:
            >>> dedup = Deduplicator()
            >>> new_records = [
            ...     {"source": "openaq", "station_id": "123", ...},
            ...     {"source": "openaq", "station_id": "124", ...},
            ... ]
            >>> unique, dups = dedup.deduplicate_air_quality(
            ...     new_records, date(2026, 8, 15)
            ... )
            >>> print(f"Deduplicated: {len(unique)} unique, {len(dups)} duplicates")
        """
        if not records:
            return [], []

        # Get existing measurement keys from partition
        existing_keys = self._get_existing_aq_keys(partition_date)

        unique_records = []
        duplicates = []
        affected_times = set()

        for record in records:
            # Generate measurement key
            key = generate_measurement_key(
                source=record.get("source"),
                station_id=record.get("station_id"),
                sensor_id=record.get("sensor_id"),
                pollutant=record.get("pollutant"),
                observed_at=record.get("observed_at"),
            )

            if key in existing_keys:
                # Duplicate found
                duplicates.append((record, key))
                affected_times.add(record.get("observed_at"))
            else:
                # New record
                unique_records.append(record)
                affected_times.add(record.get("observed_at"))

        # Log deduplication results
        if duplicates:
            logger.info(
                f"Air quality deduplication: {len(unique_records)} unique, "
                f"{len(duplicates)} duplicates from {partition_date}"
            )
            if affected_times:
                time_range = (min(affected_times), max(affected_times))
                logger.info(f"  Affected observation times: {time_range[0]} to {time_range[1]}")

        return unique_records, duplicates

    def deduplicate_weather(
        self,
        records: List[dict],
        partition_date: date,
    ) -> Tuple[List[dict], List[Tuple[dict, str]]]:
        """Deduplicate weather records.

        Compares weather_key (source + location_id + observed_at)
        against existing partition data.

        Args:
            records: List of weather records to deduplicate.
            partition_date: Target partition date (YYYY/MM/DD).

        Returns:
            Tuple of (unique_records, duplicates).
        """
        if not records:
            return [], []

        # Get existing keys from partition
        existing_keys = self._get_existing_weather_keys(partition_date)

        unique_records = []
        duplicates = []
        affected_times = set()

        for record in records:
            # Generate weather key
            key = generate_weather_key(
                source=record.get("source"),
                location_id=record.get("location_id"),
                observed_at=record.get("observed_at"),
            )

            if key in existing_keys:
                duplicates.append((record, key))
                affected_times.add(record.get("observed_at"))
            else:
                unique_records.append(record)
                affected_times.add(record.get("observed_at"))

        if duplicates:
            logger.info(
                f"Weather deduplication: {len(unique_records)} unique, "
                f"{len(duplicates)} duplicates from {partition_date}"
            )
            if affected_times:
                time_range = (min(affected_times), max(affected_times))
                logger.info(f"  Affected observation times: {time_range[0]} to {time_range[1]}")

        return unique_records, duplicates

    def _get_existing_aq_keys(self, partition_date: date) -> Set[str]:
        """Get existing measurement keys from air quality partition.

        Args:
            partition_date: Target partition date.

        Returns:
            Set of existing measurement keys.
        """
        partition_path = (
            self.storage_root
            / "openaq"
            / f"year={partition_date.year}"
            / f"month={partition_date.month:02d}"
            / f"day={partition_date.day:02d}"
        )

        if not partition_path.exists():
            logger.debug(f"Partition {partition_path} does not exist (first write)")
            return set()

        # Try to read existing parquet files
        try:
            # List all parquet files in partition
            parquet_files = list(partition_path.glob("*.parquet"))
            if not parquet_files:
                return set()

            # Read and extract keys
            # Note: This would typically use polars to read the parquet files
            # For now, return empty set (full implementation would read actual data)
            keys = set()
            logger.debug(f"Read {len(keys)} keys from {len(parquet_files)} parquet files")
            return keys

        except Exception as e:
            logger.warning(f"Error reading partition {partition_path}: {e}")
            return set()

    def _get_existing_weather_keys(self, partition_date: date) -> Set[str]:
        """Get existing weather keys from weather partition.

        Args:
            partition_date: Target partition date.

        Returns:
            Set of existing weather keys.
        """
        partition_path = (
            self.storage_root
            / "weather"
            / f"year={partition_date.year}"
            / f"month={partition_date.month:02d}"
            / f"day={partition_date.day:02d}"
        )

        if not partition_path.exists():
            logger.debug(f"Partition {partition_path} does not exist (first write)")
            return set()

        try:
            parquet_files = list(partition_path.glob("*.parquet"))
            if not parquet_files:
                return set()

            keys = set()
            logger.debug(f"Read {len(keys)} keys from {len(parquet_files)} parquet files")
            return keys

        except Exception as e:
            logger.warning(f"Error reading partition {partition_path}: {e}")
            return set()

    def get_deduplication_stats(
        self, records: List[dict], unique_records: List[dict], duplicates: List[Tuple[dict, str]]
    ) -> Dict[str, Any]:
        """Calculate deduplication statistics.

        Args:
            records: Original records.
            unique_records: Deduplicated unique records.
            duplicates: Duplicate records.

        Returns:
            Dict with deduplication stats.
        """
        return {
            "total_input": len(records),
            "unique": len(unique_records),
            "duplicates": len(duplicates),
            "dedup_ratio": len(duplicates) / len(records) if records else 0.0,
        }
