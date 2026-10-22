"""Regression test for the Parquet row-group size unit."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import polars as pl

from aq_engine.storage.parquet_io import ParquetWriter


def test_writer_passes_a_row_count_to_polars(tmp_path):
    writer = ParquetWriter(root_path=str(tmp_path))
    record = {
        "source": "openaq",
        "station_id": "1",
        "sensor_id": "2",
        "pollutant": "pm25",
        "value": 40.0,
        "unit": "ug/m3",
        "observed_at": datetime(2026, 8, 15, 12, tzinfo=timezone.utc),
        "ingested_at": datetime(2026, 8, 15, 12, 5, tzinfo=timezone.utc),
        "raw_payload_hash": "hash",
    }

    captured = {}
    original = pl.DataFrame.write_parquet

    def capture(self, file, **kwargs):
        captured.update(kwargs)
        return original(self, file, **kwargs)

    with patch.object(pl.DataFrame, "write_parquet", capture):
        writer.write_air_quality_raw([record], date(2026, 8, 15))

    assert captured["row_group_size"] == ParquetWriter.ROW_GROUP_SIZE_ROWS
    assert captured["row_group_size"] < 1_000_000
