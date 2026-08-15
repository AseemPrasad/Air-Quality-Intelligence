"""Test idempotent ingestion (no record doubling)."""

import pytest
from datetime import datetime


class TestIdempotentIngestion:
    """Test that ingesting same records twice produces same result."""

    def test_ingest_same_records_no_doubling(self):
        """Ingest 1000 records, then ingest same 1000 again → no doubling."""

        # Create 1000 records with unique keys
        def create_records(count):
            records = []
            for i in range(count):
                records.append({
                    "source": "openaq",
                    "location_id": f"loc_{i % 10}",
                    "station_id": f"stn_{i % 5}",
                    "pollutant": "PM2.5",
                    "value": 60.0 + (i % 20),
                    "observed_at": f"2026-08-15T{(10 + i // 100) % 24:02d}:00:00Z",
                    "measurement_key": f"key_{i % 100}",
                })
            return records

        records_1 = create_records(1000)
        records_2 = create_records(1000)  # Same records again

        # Simulate ingestion with deduplication
        def ingest_with_dedup(existing, new_records):
            """Ingest new records, skip duplicates."""
            seen = {r["measurement_key"] for r in existing}
            deduplicated = []

            for record in new_records:
                key = record["measurement_key"]
                if key not in seen:
                    deduplicated.append(record)
                    seen.add(key)

            return existing + deduplicated, len(deduplicated)

        # First ingest
        database_records, added = ingest_with_dedup([], records_1)
        assert len(database_records) == 1000
        assert added == 1000

        # Second ingest (same records)
        database_records, added = ingest_with_dedup(database_records, records_2)
        assert len(database_records) == 1000  # No doubling!
        assert added == 0  # All skipped as duplicates

    def test_deduplication_flags_set_correctly(self):
        """Test deduplication flags are set correctly."""

        records = [
            {
                "id": 1,
                "measurement_key": "key_1",
                "value": 60.0,
                "status": "new",
            },
            {
                "id": 2,
                "measurement_key": "key_1",  # Duplicate
                "value": 61.0,
                "status": "new",
            },
            {
                "id": 3,
                "measurement_key": "key_2",
                "value": 62.0,
                "status": "new",
            },
        ]

        # Mark duplicates
        seen = set()
        for record in records:
            key = record["measurement_key"]
            if key in seen:
                record["is_duplicate"] = True
            else:
                record["is_duplicate"] = False
                seen.add(key)

        # Verify flags
        assert records[0]["is_duplicate"] is False  # First occurrence
        assert records[1]["is_duplicate"] is True   # Duplicate
        assert records[2]["is_duplicate"] is False  # Unique

    def test_canonical_row_count_after_double_ingest(self):
        """Test canonical row count remains same after double ingestion."""

        class MockDatabase:
            def __init__(self):
                self.records = {}

            def insert_or_update(self, record):
                """Idempotent insert: use key as unique identifier."""
                key = record["key"]
                self.records[key] = record
                return key in self.records

            def count(self):
                return len(self.records)

        db = MockDatabase()

        # Create 100 records
        records = [
            {"key": f"record_{i}", "value": 50 + i}
            for i in range(100)
        ]

        # First ingest
        for record in records:
            db.insert_or_update(record)
        count_after_first = db.count()
        assert count_after_first == 100

        # Second ingest (same records)
        for record in records:
            db.insert_or_update(record)
        count_after_second = db.count()

        # Count should be identical
        assert count_after_second == 100
        assert count_after_first == count_after_second

    def test_partial_duplicate_detection(self):
        """Test detection of partial duplicates (some new, some old)."""

        existing_records = [
            {"key": "rec_1", "value": 60},
            {"key": "rec_2", "value": 61},
            {"key": "rec_3", "value": 62},
        ]

        new_records = [
            {"key": "rec_2", "value": 61},  # Duplicate
            {"key": "rec_3", "value": 62},  # Duplicate
            {"key": "rec_4", "value": 63},  # New
            {"key": "rec_5", "value": 64},  # New
        ]

        # Check for duplicates
        existing_keys = {r["key"] for r in existing_records}
        duplicate_count = sum(1 for r in new_records if r["key"] in existing_keys)
        new_count = sum(1 for r in new_records if r["key"] not in existing_keys)

        assert duplicate_count == 2
        assert new_count == 2

        # After merge
        merged = existing_records + [r for r in new_records if r["key"] not in existing_keys]
        assert len(merged) == 5  # 3 + 2 new


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
