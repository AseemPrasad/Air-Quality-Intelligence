import duckdb
import polars as pl
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class ParquetAnalyticsEngine:
    """
    High-performance analytical query engine utilizing DuckDB to execute 
    aggregations directly against local Parquet data lakes.
    """
    def __init__(self, data_dir: str = "data/processed"):
        self.data_dir = Path(data_dir)
        # Initialize an in-memory DuckDB connection
        self.conn = duckdb.connect(database=':memory:')
        logger.info("Initialized in-memory DuckDB analytics engine.")

    def execute_time_window_aggregation(self, pollutant: str, days_lookback: int = 7) -> pl.DataFrame:
        """
        Executes a zero-copy SQL aggregation over partitioned Parquet files 
        to calculate rolling hourly averages for a specific pollutant.
        """
        parquet_glob = str(self.data_dir / f"**/*{pollutant}*.parquet")
        
        query = f"""
            SELECT 
                location_id,
                DATE_TRUNC('hour', hour_start) as hour_bucket,
                AVG(observed_value) as mean_concentration,
                MAX(observed_value) as peak_concentration
            FROM read_parquet('{parquet_glob}')
            WHERE hour_start >= current_date() - INTERVAL {days_lookback} DAY
            GROUP BY 1, 2
            ORDER BY 1, 2 DESC
        """
        
        try:
            # Execute in DuckDB and return directly as a Polars DataFrame (zero-copy)
            result_df = self.conn.execute(query).pl()
            return result_df
        except Exception as e:
            logger.error(f"Failed to execute DuckDB aggregation for {pollutant}: {str(e)}")
            raise

    def close(self):
        self.conn.close()
