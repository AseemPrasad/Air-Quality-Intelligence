"""Storage layer for Parquet I/O operations.

Provides atomic, partitioned reads and writes for raw data.
"""

from aq_engine.storage.parquet_io import ParquetWriter

__all__ = ["ParquetWriter"]
