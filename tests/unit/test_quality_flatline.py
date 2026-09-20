from datetime import datetime, timedelta
from aq_engine.quality.drift import SensorDriftValidator
from aq_engine.quality.flatline import FlatlineValidator
import numpy as np
import pandas as pd
import pytest

def test_flatline_validator_detects_stuck_sensor():
  # Create sample data with 10 identical consecutive values for PM2.5
  base_time = datetime(2026, 1, 1, 0, 0)
  timestamps = [base_time + timedelta(hours=i) for i in range(10)]

  data = {
      "timestamp": timestamps,
      "station_id": ["STATION_01"] * 10,
      "parameter": ["PM2.5"] * 10,
      "value": [42.0] * 10,  # Frozen reading
  }
  df = pd.DataFrame(data)

  validator = FlatlineValidator(consecutive_hours=6)
  res = validator.validate(df)

  # First 5 readings shouldn't be flagged (less than 6 hours window)
  assert not res.iloc[0]["is_stuck_sensor"]
  # From 6th reading onwards, it must be flagged as STUCK_SENSOR
  assert res.iloc[5]["is_stuck_sensor"]
  assert res.iloc[5]["quality_flag"] == "STUCK_SENSOR"

def test_flatline_validator_passes_normal_sensor():
  base_time = datetime(2026, 1, 1, 0, 0)
  timestamps = [base_time + timedelta(hours=i) for i in range(10)]

  # Fluctuating sensor readings
  values = [42.0, 42.5, 41.8, 43.1, 42.0, 42.7, 43.0, 41.5, 42.2, 42.9]

  data = {
      "timestamp": timestamps,
      "station_id": ["STATION_01"] * 10,
      "parameter": ["PM2.5"] * 10,
      "value": values,
  }
  df = pd.DataFrame(data)

  validator = FlatlineValidator(consecutive_hours=6)
  res = validator.validate(df)

  # None of the records should be flagged
  assert not res["is_stuck_sensor"].any()

def test_sensor_drift_validator():
  base_time = datetime(2026, 1, 1, 0, 0)
  timestamps = [base_time + timedelta(hours=i) for i in range(10)]

  # Constant linearly drifting signal
  values = [10.0 + i * 0.5 for i in range(10)]

  data = {
      "timestamp": timestamps,
      "station_id": ["STATION_01"] * 10,
      "parameter": ["PM2.5"] * 10,
      "value": values,
  }
  df = pd.DataFrame(data)

  validator = SensorDriftValidator(window_size=5, slope_threshold=0.1)
  res = validator.validate(df)

  # Check that drift is flagged once window size is reached
  assert res.iloc[4]["is_drift_detected"]
  assert res.iloc[4]["quality_flag"] == "DRIFT_DETECTED"

def test_flatline_validator_empty_dataframe():
  validator = FlatlineValidator(consecutive_hours=6)
  empty_df = pd.DataFrame(
      columns=["timestamp", "station_id", "parameter", "value"]
  )
  res = validator.validate(empty_df)
  assert res.empty
  assert "is_stuck_sensor" in res.columns


def test_sensor_drift_validator_empty_dataframe():
  validator = SensorDriftValidator(window_size=5, slope_threshold=0.1)
  empty_df = pd.DataFrame(
      columns=["timestamp", "station_id", "parameter", "value"]
  )
  res = validator.validate(empty_df)
  assert res.empty
  assert "is_drift_detected" in res.columns