"""Deduplication logic for preventing duplicate observations.

Compares incoming records against existing partitions using measurement keys
to identify and filter duplicates before storage.
"""

import logging
from datetime import date
from pathlib import Path
from typing import List, Tuple, Set, Dict, Any

from aq_engine.quality.hashing import generate_measurement_key, generate_weather_key

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
        from aq_engine.storage.parquet_io import ParquetWriter

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

        Reads ``source``, ``station_id``, ``sensor_id``, ``pollutant``, and
        ``observed_at`` columns from every Parquet file in the partition and
        recomputes the SHA-256 measurement key for each row.  This mirrors
        exactly what :meth:`deduplicate_air_quality` computes for incoming
        records, so the two sets are directly comparable.

        ``measurement_key`` is not stored in the Parquet schema
        (``RawAirQualityRecord`` does not include it), hence the
        recomputation approach.

        Args:
            partition_date: Target partition date.

        Returns:
            Set of existing measurement keys.  Empty if the partition does
            not exist, contains no Parquet files, or a read error occurs.
        """
        import polars as pl

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

        try:
            parquet_files = list(partition_path.glob("*.parquet"))
            if not parquet_files:
                return set()

            key_cols = ["source", "station_id", "sensor_id", "pollutant", "observed_at"]
            keys: Set[str] = set()

            for parquet_file in parquet_files:
                df = pl.read_parquet(str(parquet_file), columns=key_cols)
                for row in df.iter_rows(named=True):
                    key = generate_measurement_key(
                        source=row["source"],
                        station_id=row["station_id"],
                        sensor_id=row["sensor_id"],
                        pollutant=row["pollutant"],
                        observed_at=row["observed_at"],
                    )
                    keys.add(key)

            logger.debug(
                f"Loaded {len(keys)} existing AQ keys from "
                f"{len(parquet_files)} parquet files in {partition_path}"
            )
            return keys

        except Exception as e:
            logger.warning(f"Error reading partition {partition_path}: {e}")
            return set()

    def _get_existing_weather_keys(self, partition_date: date) -> Set[str]:
        """Get existing weather keys from weather partition.

        Reads ``source``, ``location_id``, and ``observed_at`` columns from
        every Parquet file in the partition and recomputes the SHA-256 weather
        key for each row.  Mirrors what :meth:`deduplicate_weather` computes
        for incoming records.

        Args:
            partition_date: Target partition date.

        Returns:
            Set of existing weather keys.  Empty if the partition does not
            exist, contains no Parquet files, or a read error occurs.
        """
        import polars as pl

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

            key_cols = ["source", "location_id", "observed_at"]
            keys: Set[str] = set()

            for parquet_file in parquet_files:
                df = pl.read_parquet(str(parquet_file), columns=key_cols)
                for row in df.iter_rows(named=True):
                    key = generate_weather_key(
                        source=row["source"],
                        location_id=row["location_id"],
                        observed_at=row["observed_at"],
                    )
                    keys.add(key)

            logger.debug(
                f"Loaded {len(keys)} existing weather keys from "
                f"{len(parquet_files)} parquet files in {partition_path}"
            )
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
