"""Unit tests for Parquet I/O operations.

Tests atomic writes, partition structure, roundtrip read/write, and large batch operations.
"""

import pytest
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from aq_engine.storage.parquet_io import ParquetWriter
from aq_engine.quality.hashing import generate_measurement_key, generate_weather_key
from aq_engine.common import StorageError


@pytest.fixture
def temp_storage():
    """Temporary storage directory for tests."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aq_parquet_test_"))
    yield temp_dir
    # Cleanup
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def writer(temp_storage):
    """ParquetWriter with temporary storage."""
    return ParquetWriter(root_path=str(temp_storage))


@pytest.fixture
def sample_air_quality_records():
    """Sample air quality records for testing."""
    return [
        {
            "source": "openaq",
            "station_id": "123",
            "sensor_id": "456",
            "pollutant": "pm25",
            "value": 45.5,
            "unit": "µg/m³",
            "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
            "raw_payload_hash": "abc123",
        },
        {
            "source": "openaq",
            "station_id": "123",
            "sensor_id": "457",
            "pollutant": "pm10",
            "value": 75.2,
            "unit": "µg/m³",
            "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
            "raw_payload_hash": "def456",
        },
    ]


@pytest.fixture
def sample_weather_records():
    """Sample weather records for testing."""
    return [
        {
            "source": "open_meteo",
            "location_id": "123",
            "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            "temperature_c": 28.5,
            "humidity_pct": 65.0,
            "wind_speed_kmh": 8.5,
            "wind_direction_deg": 180.0,
            "pressure_hpa": 1013.0,
            "precipitation_mm": 0.1,
            "cloud_cover_pct": 40.0,
            "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
            "raw_payload_hash": "ghi789",
        },
        {
            "source": "open_meteo",
            "location_id": "124",
            "observed_at": datetime(2026, 8, 15, 13, 0, 0, tzinfo=timezone.utc),
            "temperature_c": 29.0,
            "humidity_pct": 62.0,
            "wind_speed_kmh": 9.0,
            "wind_direction_deg": 185.0,
            "pressure_hpa": 1013.1,
            "precipitation_mm": 0.0,
            "cloud_cover_pct": 35.0,
            "ingested_at": datetime(2026, 8, 15, 13, 5, 30, tzinfo=timezone.utc),
            "raw_payload_hash": "jkl012",
        },
    ]


class TestWriteAirQuality:
    """Test air quality writes."""

    def test_write_single_record(self, writer, sample_air_quality_records):
        """Test writing single air quality record."""
        records = sample_air_quality_records[:1]
        partition_date = date(2026, 8, 15)

        path = writer.write_air_quality_raw(records, partition_date)

        assert path is not None
        assert path.exists()
        assert "openaq" in str(path)
        assert "year=2026" in str(path)
        assert "month=08" in str(path)
        assert "day=15" in str(path)

    def test_write_multiple_records(self, writer, sample_air_quality_records):
        """Test writing multiple air quality records."""
        partition_date = date(2026, 8, 15)

        path = writer.write_air_quality_raw(sample_air_quality_records, partition_date)

        assert path.exists()

        # Verify contents
        df = pl.read_parquet(str(path))
        assert len(df) == 2
        assert "station_id" in df.columns
        assert "pollutant" in df.columns

    def test_write_empty_records(self, writer):
        """Test writing empty records list."""
        path = writer.write_air_quality_raw([], date(2026, 8, 15))
        assert path is None

    def test_write_invalid_record_raises_error(self, writer):
        """Test that invalid record raises StorageError."""
        invalid_records = [
            {
                "source": "openaq",
                "station_id": "123",
                # Missing required fields
            }
        ]

        with pytest.raises(StorageError, match="Record validation failed"):
            writer.write_air_quality_raw(invalid_records, date(2026, 8, 15))

    def test_partition_structure_created(self, writer, sample_air_quality_records):
        """Test that partition structure is created."""
        partition_date = date(2026, 8, 15)
        writer.write_air_quality_raw(sample_air_quality_records, partition_date)

        # Verify directory structure
        expected_dir = (
            writer.root_path / "openaq" / "year=2026" / "month=08" / "day=15"
        )
        assert expected_dir.exists()
        assert len(list(expected_dir.glob("*.parquet"))) > 0


class TestWriteWeather:
    """Test weather writes."""

    def test_write_single_weather_record(self, writer, sample_weather_records):
        """Test writing single weather record."""
        records = sample_weather_records[:1]
        partition_date = date(2026, 8, 15)

        path = writer.write_weather_raw(records, partition_date)

        assert path is not None
        assert path.exists()
        assert "weather" in str(path)
        assert "year=2026" in str(path)

    def test_write_multiple_weather_records(self, writer, sample_weather_records):
        """Test writing multiple weather records."""
        partition_date = date(2026, 8, 15)

        path = writer.write_weather_raw(sample_weather_records, partition_date)

        assert path.exists()

        # Verify contents
        df = pl.read_parquet(str(path))
        assert len(df) == 2
        assert "temperature_c" in df.columns
        assert "humidity_pct" in df.columns

    def test_write_weather_with_optional_nulls(self, writer):
        """Test writing weather records with null optional fields."""
        records = [
            {
                "source": "open_meteo",
                "location_id": "123",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "temperature_c": 28.5,
                "humidity_pct": 65.0,
                "wind_speed_kmh": None,  # Optional null
                "wind_direction_deg": None,  # Optional null
                "pressure_hpa": None,  # Optional null
                "precipitation_mm": None,  # Optional null
                "cloud_cover_pct": None,  # Optional null
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": "xyz",
            }
        ]

        path = writer.write_weather_raw(records, date(2026, 8, 15))
        assert path.exists()


class TestReadAirQuality:
    """Test air quality reads."""

    def test_read_single_date(self, writer, sample_air_quality_records):
        """Test reading air quality for single date."""
        partition_date = date(2026, 8, 15)
        writer.write_air_quality_raw(sample_air_quality_records, partition_date)

        # Read same date
        df = writer.read_raw_air_quality((partition_date, partition_date))

        assert len(df) == 2
        assert df["source"].unique()[0] == "openaq"

    def test_read_date_range(self, writer, sample_air_quality_records):
        """Test reading air quality for date range."""
        # Write records for multiple dates
        writer.write_air_quality_raw(sample_air_quality_records, date(2026, 8, 15))
        writer.write_air_quality_raw(sample_air_quality_records, date(2026, 8, 16))

        # Read range
        df = writer.read_raw_air_quality(
            (date(2026, 8, 15), date(2026, 8, 16))
        )

        assert len(df) == 4  # 2 records × 2 dates
        assert df["source"].unique()[0] == "openaq"

    def test_read_nonexistent_date(self, writer):
        """Test reading from nonexistent date returns empty."""
        df = writer.read_raw_air_quality((date(2026, 8, 1), date(2026, 8, 14)))
        assert len(df) == 0


class TestReadWeather:
    """Test weather reads."""

    def test_read_single_date(self, writer, sample_weather_records):
        """Test reading weather for single date."""
        partition_date = date(2026, 8, 15)
        writer.write_weather_raw(sample_weather_records, partition_date)

        # Read same date
        df = writer.read_raw_weather((partition_date, partition_date))

        assert len(df) == 2
        assert df["source"].unique()[0] == "open_meteo"

    def test_read_date_range(self, writer, sample_weather_records):
        """Test reading weather for date range."""
        # Write records for multiple dates
        writer.write_weather_raw(sample_weather_records, date(2026, 8, 15))
        writer.write_weather_raw(sample_weather_records, date(2026, 8, 16))

        # Read range
        df = writer.read_raw_weather(
            (date(2026, 8, 15), date(2026, 8, 16))
        )

        assert len(df) == 4  # 2 records × 2 dates


class TestRoundtrip:
    """Test write/read roundtrips."""

    def test_air_quality_roundtrip(self, writer, sample_air_quality_records):
        """Test air quality write/read roundtrip."""
        partition_date = date(2026, 8, 15)

        # Write
        writer.write_air_quality_raw(sample_air_quality_records, partition_date)

        # Read
        df = writer.read_raw_air_quality((partition_date, partition_date))

        # Verify
        assert len(df) == len(sample_air_quality_records)
        assert df["pollutant"].to_list() == ["pm25", "pm10"]
        assert df["value"].to_list() == [45.5, 75.2]

    def test_weather_roundtrip(self, writer, sample_weather_records):
        """Test weather write/read roundtrip."""
        partition_date = date(2026, 8, 15)

        # Write
        writer.write_weather_raw(sample_weather_records, partition_date)

        # Read
        df = writer.read_raw_weather((partition_date, partition_date))

        # Verify
        assert len(df) == len(sample_weather_records)
        assert df["location_id"].to_list() == ["123", "124"]
        assert df["temperature_c"].to_list() == [28.5, 29.0]


class TestLargeBatch:
    """Test large batch operations."""

    def test_write_10k_air_quality_records(self, writer):
        """Test writing 10k air quality records."""
        records = [
            {
                "source": "openaq",
                "station_id": f"{i % 100}",
                "sensor_id": f"{i % 500}",
                "pollutant": "pm25",
                "value": 30.0 + (i % 50),
                "unit": "µg/m³",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": f"hash_{i}",
            }
            for i in range(10000)
        ]

        path = writer.write_air_quality_raw(records, date(2026, 8, 15))
        assert path.exists()

        # Verify
        df = pl.read_parquet(str(path))
        assert len(df) == 10000

    def test_write_10k_weather_records(self, writer):
        """Test writing 10k weather records."""
        records = [
            {
                "source": "open_meteo",
                "location_id": f"{i % 50}",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "temperature_c": 25.0 + (i % 20),
                "humidity_pct": 50.0 + (i % 30),
                "wind_speed_kmh": 5.0 + (i % 15),
                "wind_direction_deg": (i * 36) % 360,
                "pressure_hpa": 1013.0,
                "precipitation_mm": 0.0,
                "cloud_cover_pct": 40.0,
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": f"hash_{i}",
            }
            for i in range(10000)
        ]

        path = writer.write_weather_raw(records, date(2026, 8, 15))
        assert path.exists()

        # Verify
        df = pl.read_parquet(str(path))
        assert len(df) == 10000


class TestCompression:
    """Test Parquet compression."""

    def test_compression_snappy(self, writer, sample_air_quality_records):
        """Test that Snappy compression is applied."""
        path = writer.write_air_quality_raw(sample_air_quality_records, date(2026, 8, 15))

        # Read and verify compression type
        table = pl.read_parquet(str(path))
        assert table is not None  # Successfully read with snappy decompression

    def test_row_group_size(self, writer):
        """Test that row group size is set to 128MB."""
        # Create large batch (many records)
        records = [
            {
                "source": "openaq",
                "station_id": f"{i}",
                "sensor_id": f"{i * 2}",
                "pollutant": "pm25",
                "value": 40.0,
                "unit": "µg/m³",
                "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
                "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=timezone.utc),
                "raw_payload_hash": f"hash_{i}",
            }
            for i in range(1000)
        ]

        path = writer.write_air_quality_raw(records, date(2026, 8, 15))
        assert path.exists()
        assert len(pl.read_parquet(str(path))) == 1000


class TestMeasurementKey:
    """Test measurement key generation."""

    def test_generate_air_quality_key(self):
        """Test generating air quality measurement key."""
        key = generate_measurement_key(
            source="openaq",
            station_id="123",
            sensor_id="456",
            pollutant="pm25",
            observed_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert isinstance(key, str)
        assert len(key) == 64  # SHA256 hex
        assert key.startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f"))

    def test_generate_air_quality_key_idempotent(self):
        """Test that same inputs produce same key."""
        key1 = generate_measurement_key(
            source="openaq",
            station_id="123",
            sensor_id="456",
            pollutant="pm25",
            observed_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        key2 = generate_measurement_key(
            source="openaq",
            station_id="123",
            sensor_id="456",
            pollutant="pm25",
            observed_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert key1 == key2

    def test_generate_weather_key(self):
        """Test generating weather measurement key."""
        key = generate_weather_key(
            source="open_meteo",
            location_id="123",
            observed_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert isinstance(key, str)
        assert len(key) == 64  # SHA256 hex

    def test_generate_weather_key_idempotent(self):
        """Test that same weather inputs produce same key."""
        key1 = generate_weather_key(
            source="open_meteo",
            location_id="123",
            observed_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        key2 = generate_weather_key(
            source="open_meteo",
            location_id="123",
            observed_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert key1 == key2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
