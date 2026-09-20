"""Flatline / Stuck-value sensor validation module."""

from typing import List, Optional
import pandas as pd

class FlatlineValidator:
  """Detects frozen or stuck sensor readings where variance is zero over a window."""

  def __init__(self, consecutive_hours: int = 6):
    self.consecutive_hours = consecutive_hours

  def validate(
      self,
      df: pd.DataFrame,
      value_col: str = "value",
      station_col: str = "station_id",
      param_col: str = "parameter",
      timestamp_col: str = "timestamp",
  ) -> pd.DataFrame:
    """Calculates rolling variance per station and parameter.

    Flags records as STUCK_SENSOR when rolling variance is 0 over
    N consecutive hours.
    """
    if df.empty:
      df["is_stuck_sensor"] = False
      df["quality_flag"] = None
      return df

    result_df = df.copy()

    # Sort to ensure rolling computations are chronological
    if timestamp_col in result_df.columns:
      result_df = result_df.sort_values(
          by=[station_col, param_col, timestamp_col]
      )

    # Compute rolling variance over N records per group
    rolling_var = result_df.groupby([station_col, param_col])[
        value_col
    ].transform(
        lambda x: x.rolling(
            window=self.consecutive_hours, min_periods=self.consecutive_hours
        ).var()
    )

    # Variance equal to 0 indicates identical readings over the window
    stuck_mask = rolling_var == 0.0

    result_df["is_stuck_sensor"] = stuck_mask

    if "quality_flag" not in result_df.columns:
      result_df["quality_flag"] = None

    result_df.loc[stuck_mask, "quality_flag"] = "STUCK_SENSOR"

    return result_df