# Air Quality Intelligence Platform: Data Contracts

## Overview

Data contracts define the canonical schemas for all data flowing through the platform. All data flowing into the system must conform to these contracts; violations are quarantined and reported.

## Air Quality Measurements

### Measurement Schema

**Source:** OpenAQ API  
**Frequency:** Hourly  
**Grain:** Per-station observations  
**Volume:** ~1,200 records/hour across all locations

```json
{
  "location_id": "kolkata_001",
  "station_id": "stn_001",
  "pollutant": "PM2.5",
  "value_ug_m3": 65.5,
  "timestamp": "2026-08-15T10:00:00Z",
  "source": "openaq",
  "external_id": "openaq_12345",
  "source_country": "India",
  "is_mobile": false,
  "has_geo": true
}
```

### Field Definitions

| Field | Type | Required | Range/Values | Notes |
|-------|------|----------|--------------|-------|
| `location_id` | string | ✅ | Any | Platform identifier |
| `station_id` | string | ✅ | Any | Unique per station |
| `pollutant` | string | ✅ | `PM2.5`, `PM10`, `NO2`, `O3` | Air pollutant |
| `value_ug_m3` | float | ✅ | [0, 1000] | µg/m³ (micrograms/m³) |
| `timestamp` | ISO 8601 | ✅ | UTC, not > now | Observation time |
| `source` | string | ✅ | `openaq` | Data source |
| `external_id` | string | ✅ | Any | Source's record ID |
| `source_country` | string | ✅ | ISO 3166-1 | Origin country |
| `is_mobile` | bool | ❌ | true/false | Mobile sensor? |
| `has_geo` | bool | ❌ | true/false | Has coordinates? |

### Quality Rules

**VALID:** All rules pass
```python
- not null(value_ug_m3, timestamp, location_id)
- 0 <= value_ug_m3 <= 1000
- timestamp <= now + 1 hour
- timestamp >= now - 10 years
- station_id in known_stations
```

**SUSPICIOUS:** Data is present but anomalous
```python
- duplicates (same measurement_key, within 6 hours)
- flatlines (3+ identical values)
- extreme_outliers (z_score > 6)
- future_timestamp (> now + 1 hour)
```

**INVALID:** Reject immediately
```python
- null(value_ug_m3) or null(timestamp)
- value_ug_m3 < 0
- station_id not in known_stations
- malformed_json
```

### Measurement Key (Idempotency)

**Definition:** SHA256 hash for deduplication

```python
measurement_key = SHA256(
    source +
    location_id +
    station_id +
    pollutant +
    timestamp
)
```

**Purpose:** Detect and skip duplicate ingestions (same record processed twice)

**Example:**
```
SHA256("openaq" + "kolkata_001" + "stn_001" + "PM2.5" + "2026-08-15T10:00:00Z")
= "a1b2c3d4e5f6g7h8..."
```

## Weather Observations

### Weather Schema

**Source:** Open-Meteo API  
**Frequency:** Hourly  
**Grain:** Per-location weather  
**Volume:** ~450 records/hour

```json
{
  "location_id": "kolkata_001",
  "timestamp": "2026-08-15T10:00:00Z",
  "temperature_c": 32.5,
  "humidity_pct": 75,
  "wind_speed_kmh": 12.0,
  "wind_direction_deg": 230,
  "pressure_hpa": 1013.25,
  "precipitation_mm": 0.5,
  "source": "open_meteo",
  "external_id": "grid_22.57_88.36"
}
```

### Field Definitions

| Field | Type | Required | Range | Units |
|-------|------|----------|-------|-------|
| `location_id` | string | ✅ | Any | - |
| `timestamp` | ISO 8601 | ✅ | UTC | - |
| `temperature_c` | float | ✅ | [-50, 60] | Celsius |
| `humidity_pct` | float | ❌ | [0, 100] | % |
| `wind_speed_kmh` | float | ❌ | [0, 100] | km/h |
| `wind_direction_deg` | int | ❌ | [0, 360) | degrees |
| `pressure_hpa` | float | ❌ | [900, 1100] | hPa |
| `precipitation_mm` | float | ❌ | [0, 500] | mm |
| `source` | string | ✅ | `open_meteo` | - |
| `external_id` | string | ✅ | Grid ID | - |

### Quality Rules

**VALID:**
```python
- not null(temperature_c, timestamp, location_id)
- -50 <= temperature_c <= 60
- humidity_pct is null OR (0 <= humidity_pct <= 100)
- wind_speed_kmh is null OR (0 <= wind_speed_kmh <= 100)
- timestamp <= now + 1 hour
```

**SUSPICIOUS:**
```python
- duplicates (same external_id + timestamp)
- extreme_temperature (< -40 OR > 50)
- inconsistent_wind (wind_direction without wind_speed)
```

**INVALID:**
```python
- null(temperature_c, timestamp, location_id)
- temperature_c < -50 OR > 60
- null(external_id)
```

## Hourly Facts (Aggregated)

### Facts Schema

**Derived from:** Raw measurements aggregated hourly per location  
**Storage:** Parquet (date-partitioned)  
**Retention:** 3 years  
**Grain:** 1 fact per location per hour

```json
{
  "location_id": "kolkata_001",
  "hour_start": "2026-08-15T10:00:00Z",
  "hour_end": "2026-08-15T11:00:00Z",
  "pollutant": "PM2.5",
  "mean_value": 62.3,
  "median_value": 61.5,
  "min_value": 42.1,
  "max_value": 75.3,
  "stddev_value": 8.2,
  "observation_count": 12,
  "coverage_pct": 100.0,
  "quality_flag": "VALID"
}
```

### Field Definitions

| Field | Type | Required | Calculation |
|-------|------|----------|------------|
| `location_id` | string | ✅ | From measurements |
| `hour_start` | timestamp | ✅ | Truncated to hour |
| `hour_end` | timestamp | ✅ | hour_start + 1h |
| `pollutant` | string | ✅ | PM2.5 |
| `mean_value` | float | ✅ | AVG(value) |
| `median_value` | float | ✅ | PERCENTILE(value, 0.5) |
| `min_value` | float | ✅ | MIN(value) |
| `max_value` | float | ✅ | MAX(value) |
| `stddev_value` | float | ✅ | STDDEV(value) |
| `observation_count` | int | ✅ | COUNT(*) |
| `coverage_pct` | float | ✅ | (count / expected) * 100 |
| `quality_flag` | string | ✅ | VALID/SUSPICIOUS/INVALID |

## Baselines (365-Day Statistics)

### Baseline Schema

**Computed from:** 365 days of hourly facts, grouped by (month, hour_of_day)  
**Updated:** Daily after new facts  
**Grain:** 1 baseline per (location, pollutant, month, hour)  
**Total rows:** Locations × Pollutants × 12 months × 24 hours

```json
{
  "location_id": "kolkata_001",
  "pollutant": "PM2.5",
  "month": 8,
  "hour_of_day": 14,
  "observation_count": 62,
  "median": 55.0,
  "mad": 8.5,
  "p25": 48.0,
  "p50": 55.0,
  "p75": 62.1,
  "p90": 71.3,
  "p95": 78.5,
  "p99": 92.1
}
```

### Field Definitions

| Field | Type | Calculation |
|-------|------|------------|
| `location_id` | string | - |
| `pollutant` | string | PM2.5 |
| `month` | int | 1-12 |
| `hour_of_day` | int | 0-23 |
| `observation_count` | int | COUNT(facts in this bucket) |
| `median` | float | PERCENTILE(value, 0.50) |
| `mad` | float | Median Absolute Deviation |
| `p25` | float | PERCENTILE(value, 0.25) |
| `p50` | float | PERCENTILE(value, 0.50) |
| `p75` | float | PERCENTILE(value, 0.75) |
| `p90` | float | PERCENTILE(value, 0.90) |
| `p95` | float | PERCENTILE(value, 0.95) |
| `p99` | float | PERCENTILE(value, 0.99) |

## Quality Classifications

### Severity Levels

Used throughout the platform to categorize anomalies and events.

#### 1. NORMAL (Low Risk)

**Definition:** Observation within expected range

```
Z-Score: < 2.0
Observation: <= baseline_median + (2 × MAD)
Risk: None
Action: None
```

**Example:** 
- Baseline median: 55 µg/m³
- MAD: 8.5
- Threshold: 55 + (2 × 8.5) = 72 µg/m³
- Observation: 65 µg/m³ → **NORMAL** ✓

#### 2. LOW (Moderate Risk)

**Definition:** Observation slightly above expected

```
Z-Score: 2.0 to 3.0
Observation: baseline_median + (2-3 × MAD)
Risk: Moderate air quality
Action: Monitor
```

**Example:**
- Observation: 76 µg/m³ → **LOW** (between 2-3 MAD)

#### 3. HIGH (High Risk)

**Definition:** Significant exceedance

```
Z-Score: 3.0 to 5.0
Observation: baseline_median + (3-5 × MAD)
Risk: Poor air quality
Action: Alert & notify
```

**Example:**
- Observation: 99 µg/m³ → **HIGH** (between 3-5 MAD)

#### 4. EXTREME (Critical)

**Definition:** Severe pollution

```
Z-Score: >= 5.0
Observation: >= baseline_median + (5 × MAD)
Risk: Very poor air quality
Action: Issue health warnings
```

**Example:**
- Observation: 125 µg/m³ → **EXTREME** (> 5 MAD)

### Quality Flags

#### VALID
- All validation rules passed
- Data quality score: HIGH
- Confidence: 100%

#### SUSPICIOUS
- Minor data quality issues
- Requires investigation but usable
- Examples:
  - Potential duplicate (same value, nearby time)
  - Slight flatline (same value 2 consecutive hours)
  - Minor outlier (z-score 4-6)

#### INVALID
- Failed critical validation rules
- Quarantined, not used in analytics
- Examples:
  - Null required field
  - Negative value
  - Unknown station
  - Future timestamp

## Feature Engineering

### Feature Set (46 Total)

**Lags (24 features):**
```python
pm25_lag_1h   # 1 hour ago
pm25_lag_6h   # 6 hours ago
pm25_lag_12h  # 12 hours ago
pm25_lag_24h  # 1 day ago
... (20 more lags)
```

**Rolling Windows (12 features):**
```python
pm25_rolling_mean_6h    # 6-hour moving average
pm25_rolling_mean_24h   # 24-hour moving average
pm25_rolling_std_6h     # 6-hour rolling stdev
... (9 more windows)
```

**Weather (4 features):**
```python
temperature_c      # Current temperature
humidity_pct       # Relative humidity
wind_speed_kmh     # Wind speed
pressure_hpa       # Atmospheric pressure
```

**Temporal (6 features):**
```python
hour_of_day        # 0-23
day_of_week        # 0-6 (Monday-Sunday)
day_of_month       # 1-31
month              # 1-12
quarter            # 1-4
is_weekend         # Boolean
```

### Critical Constraint: Future Leakage Prevention

**Rule:** All features use `reference_time`, never `target_time`

```python
# ✅ CORRECT: Reference time (historical data)
pm25_lag_1h = facts[reference_time - 1h].mean_value

# ❌ WRONG: Target time (future data, causes leakage)
pm25_lag_1h = facts[target_time - 1h].mean_value
```

## Time-Series Splits

### Chronological Split (Production-Like)

**Data:** 90 days of history (144,000 records)

```
Train:      Days 1-63  (70%, 100,800 records)
Validation: Days 64-77 (15%, 21,600 records)
Test:       Days 78-90 (15%, 21,600 records)

Strict ordering: train < validation < test
No overlap, no shuffling
```

### Split Metrics

```python
train_size = 100800
val_size = 21600
test_size = 21600
total = 144000

train_ratio = 100800 / 144000 = 0.70
val_ratio = 21600 / 144000 = 0.15
test_ratio = 21600 / 144000 = 0.15
```

## Prediction Targets

### Multi-Horizon Forecasts

**Target variable:** PM2.5 concentration (µg/m³)

```json
{
  "reference_time": "2026-08-15T10:00:00Z",
  "target_time_1h": "2026-08-15T11:00:00Z",
  "target_time_3h": "2026-08-15T13:00:00Z",
  "target_time_6h": "2026-08-15T16:00:00Z",
  "target_pm25_1h": 62.0,
  "target_pm25_3h": 64.0,
  "target_pm25_6h": 66.0
}
```

### Prediction Intervals

**Empirical percentiles from residuals:**

```python
# From 365 days of residuals
lower_bound = percentile(residuals, 5)      # 5th percentile
point_estimate = mean(predictions)          # Point forecast
upper_bound = percentile(residuals, 95)     # 95th percentile

confidence = (95 - 5) / 100 = 0.90
```

## Example Data Journey

### Step 1: Raw Ingestion
```
OpenAQ API → {value: 65.5, timestamp: "2026-08-15T10:00:00Z", location_id: "kolkata_001"}
Validation: ✓ VALID
Deduplicate: measurement_key = "a1b2c3..." (new)
Store: Parquet + PostgreSQL watermark
```

### Step 2: Hourly Aggregation
```
All observations for kolkata_001, 2026-08-15 10:00-11:00 →
  mean: 62.3, median: 61.5, stddev: 8.2
→ Hourly fact (1 row)
```

### Step 3: Baseline Comparison
```
Hour fact: 62.3 µg/m³ (2026-08-15 10:00, August, hour 10)
Baseline: median=55.0, MAD=8.5
Z-score: (62.3 - 55.0) / 8.5 = 0.86
Severity: NORMAL (< 2.0)
```

### Step 4: Feature Engineering
```
Reference time: 2026-08-15 10:00
Features:
  - pm25_lag_1h: 58.2 (from 09:00)
  - pm25_lag_6h: 52.1 (from 04:00)
  - temperature_c: 32.5 (current)
  - hour_of_day: 10
  ...
```

### Step 5: Inference
```
Features → Model → Predictions:
  1h: 62.0 ± [55, 70]
  3h: 64.0 ± [54, 75]
  6h: 66.0 ± [55, 78]
Store: PostgreSQL predictions table
```

### Step 6: API Response
```
GET /locations/kolkata_001/forecast →
{
  "generated_at": "2026-08-15T10:30:00Z",
  "forecasts": [
    {
      "horizon_minutes": 60,
      "predicted_pm25": 62.0,
      "lower_bound": 55.0,
      "upper_bound": 70.0,
      "confidence": 0.90
    }
  ]
}
```

---

**Next:** See [Anomaly Detection Logic](03-anomaly-detection-logic.md) for detection rules.
