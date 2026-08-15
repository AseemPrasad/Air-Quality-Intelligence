"""Parquet I/O operations for raw data storage.

Provides atomic, partitioned writes and reads for air quality and weather data.
"""

import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

import polars as pl

from aq_engine.common import ensure_utc, date_partition_path, StorageError
from aq_engine.quality.contracts import RawAirQualityRecord, RawWeatherRecord


logger = logging.getLogger(__name__)


class ParquetWriter:
    """Atomic writer for Parquet-partitioned data.

    Writes records to Parquet files with partition structure:
    - data/raw/openaq/year=YYYY/month=MM/day=DD/
    - data/raw/weather/year=YYYY/month=MM/day=DD/

    Uses atomic writes (temp → rename) to ensure no partial data.
    Compresses with snappy (fast, reasonable compression).

    Example:
        >>> writer = ParquetWriter(root_path="data/raw")
        >>> records = [
        ...     {"source": "openaq", "station_id": "123", ...},
        ...     {"source": "openaq", "station_id": "124", ...},
        ... ]
        >>> path = writer.write_air_quality_raw(records, date(2026, 8, 15))
        >>> print(f"Wrote to {path}")
    """

    def __init__(self, root_path: str = "data/raw"):
        """Initialize Parquet writer.

        Args:
            root_path: Root directory for raw data storage.
        """
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"ParquetWriter initialized with root_path: {self.root_path}")

    def write_air_quality_raw(
        self,
        records: List[dict],
        partition_date: date,
    ) -> Path:
        """Write air quality records to Parquet partition.

        Validates records against RawAirQualityRecord schema,
        writes to date partition with atomic semantics.

        Args:
            records: List of air quality record dicts.
            partition_date: Date for partition (year/month/day).

        Returns:
            Path to written Parquet file.

        Raises:
            StorageError: On validation or write failure.

        Example:
            >>> records = [
            ...     {
            ...         "source": "openaq",
            ...         "station_id": "123",
            ...         "sensor_id": "456",
            ...         "pollutant": "pm25",
            ...         "value": 45.5,
            ...         "unit": "µg/m³",
            ...         "observed_at": datetime.now(timezone.utc),
            ...         "ingested_at": datetime.now(timezone.utc),
            ...         "raw_payload_hash": "abc123",
            ...     }
            ... ]
            >>> path = writer.write_air_quality_raw(records, date(2026, 8, 15))
        """
        if not records:
            logger.warning("No records to write for air quality")
            return None

        try:
            # Validate records against schema
            validated_records = []
            for record in records:
                try:
                    validated = RawAirQualityRecord(**record)
                    validated_records.append(validated.model_dump())
                except Exception as e:
                    raise StorageError(
                        f"Record validation failed: {str(e)}",
                        context={"record": str(record)[:500]},
                    ) from e

            # Convert to Polars DataFrame
            df = pl.DataFrame(validated_records)

            # Write to partition
            output_path = self._write_partition(
                df=df,
                source="openaq",
                partition_date=partition_date,
                num_records=len(records),
            )

            return output_path

        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"Failed to write air quality records: {str(e)}",
                context={"record_count": len(records), "partition_date": str(partition_date)},
            ) from e

    def write_weather_raw(
        self,
        records: List[dict],
        partition_date: date,
    ) -> Path:
        """Write weather records to Parquet partition.

        Validates records against RawWeatherRecord schema,
        writes to date partition with atomic semantics.

        Args:
            records: List of weather record dicts.
            partition_date: Date for partition (year/month/day).

        Returns:
            Path to written Parquet file.

        Raises:
            StorageError: On validation or write failure.

        Example:
            >>> records = [
            ...     {
            ...         "source": "open_meteo",
            ...         "location_id": "123",
            ...         "observed_at": datetime.now(timezone.utc),
            ...         "temperature_c": 28.5,
            ...         "humidity_pct": 65.0,
            ...         "wind_speed_kmh": 8.5,
            ...         "wind_direction_deg": 180.0,
            ...         "pressure_hpa": 1013.0,
            ...         "precipitation_mm": 0.1,
            ...         "cloud_cover_pct": 40.0,
            ...         "ingested_at": datetime.now(timezone.utc),
            ...         "raw_payload_hash": "abc123",
            ...     }
            ... ]
            >>> path = writer.write_weather_raw(records, date(2026, 8, 15))
        """
        if not records:
            logger.warning("No records to write for weather")
            return None

        try:
            # Validate records against schema
            validated_records = []
            for record in records:
                try:
                    validated = RawWeatherRecord(**record)
                    validated_records.append(validated.model_dump())
                except Exception as e:
                    raise StorageError(
                        f"Record validation failed: {str(e)}",
                        context={"record": str(record)[:500]},
                    ) from e

            # Convert to Polars DataFrame
            df = pl.DataFrame(validated_records)

            # Write to partition
            output_path = self._write_partition(
                df=df,
                source="weather",
                partition_date=partition_date,
                num_records=len(records),
            )

            return output_path

        except StorageError:
            raise
        except Exception as e:
            raise StorageError(
                f"Failed to write weather records: {str(e)}",
                context={"record_count": len(records), "partition_date": str(partition_date)},
            ) from e

    def _write_partition(
        self,
        df: pl.DataFrame,
        source: str,
        partition_date: date,
        num_records: int,
    ) -> Path:
        """Atomically write DataFrame to partition.

        Uses temp file → rename for atomic semantics.

        Args:
            df: Polars DataFrame to write.
            source: Source name (openaq, weather).
            partition_date: Partition date.
            num_records: Number of records (for logging).

        Returns:
            Path to written file.

        Raises:
            StorageError: On write failure.
        """
        # Construct partition path
        partition_path = date_partition_path(partition_date)
        storage_dir = self.root_path / source / partition_path
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Final output path
        final_path = storage_dir / f"records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"

        try:
            # Write to temporary file first
            with tempfile.NamedTemporaryFile(
                suffix=".parquet",
                dir=storage_dir,
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)

            # Write Parquet
            df.write_parquet(
                str(tmp_path),
                compression="snappy",
                row_group_size=128 * 1024 * 1024,  # 128 MB row groups
            )

            # Atomic rename
            tmp_path.rename(final_path)

            logger.info(
                f"Wrote {num_records} {source} records to {final_path.relative_to(self.root_path)}"
            )

            return final_path

        except Exception as e:
            # Clean up temp file if it exists
            if tmp_path.exists():
                tmp_path.unlink()

            raise StorageError(
                f"Failed to write partition: {str(e)}",
                context={
                    "source": source,
                    "partition_date": str(partition_date),
                    "target_path": str(final_path),
                },
            ) from e

    def read_raw_air_quality(
        self,
        date_range: Tuple[date, date],
    ) -> pl.DataFrame:
        """Read air quality data for date range.

        Scans partition structure and reads all matching Parquet files.

        Args:
            date_range: Tuple of (start_date, end_date) inclusive.

        Returns:
            Polars DataFrame with all matching records.

        Raises:
            StorageError: If no data found or read fails.

        Example:
            >>> df = reader.read_raw_air_quality(
            ...     (date(2026, 8, 1), date(2026, 8, 31))
            ... )
            >>> print(f"Read {len(df)} records")
        """
        return self._read_partition_range(
            source="openaq",
            date_range=date_range,
        )

    def read_raw_weather(
        self,
        date_range: Tuple[date, date],
    ) -> pl.DataFrame:
        """Read weather data for date range.

        Scans partition structure and reads all matching Parquet files.

        Args:
            date_range: Tuple of (start_date, end_date) inclusive.

        Returns:
            Polars DataFrame with all matching records.

        Raises:
            StorageError: If no data found or read fails.

        Example:
            >>> df = reader.read_raw_weather(
            ...     (date(2026, 8, 1), date(2026, 8, 31))
            ... )
            >>> print(f"Read {len(df)} records")
        """
        return self._read_partition_range(
            source="weather",
            date_range=date_range,
        )

    def _read_partition_range(
        self,
        source: str,
        date_range: Tuple[date, date],
    ) -> pl.DataFrame:
        """Read all Parquet files in date range.

        Args:
            source: Source name (openaq, weather).
            date_range: Tuple of (start_date, end_date) inclusive.

        Returns:
            Combined Polars DataFrame.

        Raises:
            StorageError: If read fails.
        """
        from aq_engine.common import get_date_range

        start_date, end_date = date_range

        # Find all partition directories in range
        source_dir = self.root_path / source
        if not source_dir.exists():
            logger.warning(f"Source directory not found: {source_dir}")
            return pl.DataFrame()

        # Collect all Parquet files
        parquet_files = []

        for partition_date in get_date_range(
            datetime.combine(start_date, datetime.min.time()).replace(tzinfo=None),
            datetime.combine(end_date, datetime.max.time()).replace(tzinfo=None),
        ):
            partition_path = date_partition_path(partition_date.date())
            partition_dir = source_dir / partition_path

            if partition_dir.exists():
                # Find all .parquet files in this partition
                parquet_files.extend(partition_dir.glob("*.parquet"))

        if not parquet_files:
            logger.warning(f"No Parquet files found for {source} in {date_range}")
            return pl.DataFrame()

        try:
            # Read all files and combine
            dfs = []
            for parquet_file in sorted(parquet_files):
                df = pl.read_parquet(str(parquet_file))
                dfs.append(df)

            if not dfs:
                return pl.DataFrame()

            combined_df = pl.concat(dfs, how="vertical")

            logger.info(
                f"Read {len(combined_df)} {source} records from {len(parquet_files)} files "
                f"in range {date_range}"
            )

            return combined_df

        except Exception as e:
            raise StorageError(
                f"Failed to read Parquet files: {str(e)}",
                context={
                    "source": source,
                    "date_range": str(date_range),
                    "file_count": len(parquet_files),
                },
            ) from e
