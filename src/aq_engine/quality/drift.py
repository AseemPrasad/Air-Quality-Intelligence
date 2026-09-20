"""Sensor calibration drift validation module."""

import numpy as np
import pandas as pd

class SensorDriftValidator:
  """Detects gradual upward or downward signal drift over extended horizons."""

  def __init__(self, window_size: int = 168, slope_threshold: float = 0.05):
    """window_size: Number of records (e.g., 168 for 7 days at hourly resolution)

    slope_threshold: Slope rate above which trend is flagged as drift
    """
    self.window_size = window_size
    self.slope_threshold = slope_threshold

  def _compute_slope(self, series: pd.Series) -> float:
    if len(series) < self.window_size or series.isna().any():
      return 0.0
    x = np.arange(len(series))
    y = series.values
    # Fit line y = mx + c and return slope m
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)

  def validate(
      self,
      df: pd.DataFrame,
      value_col: str = "value",
      station_col: str = "station_id",
      param_col: str = "parameter",
      timestamp_col: str = "timestamp",
  ) -> pd.DataFrame:
    """Calculates rolling trend slope per station and parameter.

    Flags records as DRIFT_DETECTED when slope exceeds threshold.
    """
    if df.empty:
      df["is_drift_detected"] = False
      return df

    result_df = df.copy()

    if timestamp_col in result_df.columns:
      result_df = result_df.sort_values(
          by=[station_col, param_col, timestamp_col]
      )

    rolling_slope = result_df.groupby([station_col, param_col])[
        value_col
    ].transform(
        lambda x: x.rolling(
            window=self.window_size, min_periods=self.window_size
        ).apply(self._compute_slope, raw=False)
    )

    drift_mask = rolling_slope.abs() >= self.slope_threshold

    result_df["is_drift_detected"] = drift_mask

    if "quality_flag" not in result_df.columns:
      result_df["quality_flag"] = None

    result_df.loc[drift_mask, "quality_flag"] = "DRIFT_DETECTED"

    return result_df