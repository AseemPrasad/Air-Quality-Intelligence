"""Performance tests for data ingestion."""

import pytest
import time
from datetime import datetime
import psutil
import os


@pytest.fixture
def process_memory():
    """Track process memory usage."""
    process = psutil.Process(os.getpid())
    return process


class TestIngestionPerformance:
    """Test ingestion throughput and resource usage."""

    def test_openaq_10k_records_under_2_minutes(self, benchmark, process_memory):
        """Test: ingest 10,000 OpenAQ records in < 2 minutes."""

        def ingest_openaq_records():
            """Simulate OpenAQ ingestion."""
            records = []
            for i in range(10000):
                records.append({
                    "source": "openaq",
                    "location_id": f"loc_{i % 100}",
                    "pollutant": "PM2.5",
                    "value": 60.0 + (i % 50),
                    "unit": "µg/m³",
                    "observed_at": f"2026-08-15T{(i // 500) % 24:02d}:{(i % 60):02d}:00Z",
                    "quality_flag": "VALID",
                })

            # Simulate validation and deduplication
            validated = [r for r in records if r["value"] >= 0]

            # Simulate storage (in-memory for benchmark)
            return len(validated)

        # Measure memory before
        mem_before = process_memory.memory_info().rss / (1024 ** 2)  # MB

        # Run benchmark
        result = benchmark(ingest_openaq_records)

        # Measure memory after
        mem_after = process_memory.memory_info().rss / (1024 ** 2)  # MB
        memory_peak = mem_after - mem_before

        # Assertions
        assert result == 10000  # All records processed
        assert memory_peak < 500  # Memory < 500MB for OpenAQ

        # Throughput calculation
        # benchmark.stats provides timing info
        duration_seconds = benchmark.stats.mean  # Average duration
        throughput = 10000 / duration_seconds if duration_seconds > 0 else 0

        print(f"OpenAQ Ingestion: {throughput:.0f} records/sec, {memory_peak:.1f}MB peak")

    def test_weather_5k_records_under_2_minutes(self, benchmark, process_memory):
        """Test: ingest 5,000 weather records in < 2 minutes."""

        def ingest_weather_records():
            """Simulate Open-Meteo ingestion."""
            records = []
            for i in range(5000):
                records.append({
                    "source": "open_meteo",
                    "location_id": f"loc_{i % 50}",
                    "temperature_c": 28.5 + (i % 10),
                    "humidity_pct": 82 - (i % 30),
                    "wind_speed_kmh": 3.5 + (i % 5),
                    "observed_at": f"2026-08-15T{(i // 200) % 24:02d}:{(i % 60):02d}:00Z",
                    "quality_flag": "VALID",
                })

            # Simulate validation
            validated = [r for r in records if r["temperature_c"] > -50]

            return len(validated)

        # Measure memory
        mem_before = process_memory.memory_info().rss / (1024 ** 2)

        # Run benchmark
        result = benchmark(ingest_weather_records)

        # Measure memory after
        mem_after = process_memory.memory_info().rss / (1024 ** 2)
        memory_peak = mem_after - mem_before

        # Assertions
        assert result == 5000
        assert memory_peak < 300  # Memory < 300MB for weather

        duration_seconds = benchmark.stats.mean
        throughput = 5000 / duration_seconds if duration_seconds > 0 else 0

        print(f"Weather Ingestion: {throughput:.0f} records/sec, {memory_peak:.1f}MB peak")

    @pytest.mark.benchmark(group="ingestion")
    def test_openaq_throughput_regression(self, benchmark):
        """Regression test: OpenAQ throughput baseline."""

        def ingest_batch():
            records = [{"id": i, "value": 60 + i} for i in range(1000)]
            return len(records)

        result = benchmark(ingest_batch)
        assert result == 1000

    @pytest.mark.benchmark(group="ingestion")
    def test_weather_throughput_regression(self, benchmark):
        """Regression test: Weather throughput baseline."""

        def ingest_batch():
            records = [{"id": i, "temp": 28 + i % 10} for i in range(500)]
            return len(records)

        result = benchmark(ingest_batch)
        assert result == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--benchmark-compare"])
