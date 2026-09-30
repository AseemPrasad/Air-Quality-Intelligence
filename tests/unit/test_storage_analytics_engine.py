"""Unit tests for ParquetAnalyticsEngine."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import polars as pl
import pytest
from aq_engine.storage.analytics_engine import ParquetAnalyticsEngine


class TestParquetAnalyticsEngine:
    """Test ParquetAnalyticsEngine initialization and query execution."""

    def test_init_and_close(self, tmp_path):
        engine = ParquetAnalyticsEngine(data_dir=str(tmp_path))
        assert engine.conn is not None
        engine.close()

    def test_execute_time_window_aggregation(self, tmp_path):
        engine = ParquetAnalyticsEngine(data_dir=str(tmp_path))

        mock_pl_df = pl.DataFrame({
            "location_id": ["loc_1"],
            "hour_bucket": [datetime(2026, 8, 15, 10, 0, tzinfo=UTC)],
            "mean_concentration": [55.2],
            "peak_concentration": [78.4],
        })
        mock_conn = MagicMock()
        mock_conn.execute.return_value.pl.return_value = mock_pl_df
        engine.conn = mock_conn

        res = engine.execute_time_window_aggregation("pm25", days_lookback=7)
        assert not res.is_empty()
        assert "mean_concentration" in res.columns

        engine.close()

    def test_execute_failure_raises(self, tmp_path):
        engine = ParquetAnalyticsEngine(data_dir=str(tmp_path))
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("DuckDB Query Error")
        engine.conn = mock_conn
        with pytest.raises(Exception, match="DuckDB Query Error"):
            engine.execute_time_window_aggregation("pm25")
        engine.close()
