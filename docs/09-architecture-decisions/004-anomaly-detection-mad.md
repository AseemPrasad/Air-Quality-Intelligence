# ADR 004: Median Absolute Deviation (MAD) for Anomaly Detection

**Date:** 2026-08-15  
**Status:** ACCEPTED  
**Stakeholders:** Data Science, Analytics Engineering

## Context

The platform needs real-time anomaly detection for air quality measurements. The algorithm must:

1. **Handle historical outliers:** Past 1-2 extreme pollution events shouldn't affect today's baseline
2. **Work with sparse data:** Some months have < 30 observations
3. **Be interpretable:** Domain experts should understand why a measurement is flagged
4. **Be robust:** Resistant to measurement errors and sensor glitches
5. **Require no training:** Use only historical statistics

## Decision

**Adopt Median Absolute Deviation (MAD) with percentile fallback**

```python
# Normal calculation
baseline_median = percentile(history, 0.50)
baseline_mad = median(abs(history - baseline_median))

# Z-score (MAD-based)
z_score = (current_value - baseline_median) / (1.4826 * baseline_mad)

# Fallback (when MAD = 0)
percentile_rank = percentile_rank(current_value, history)
severity = calculate_severity_from_percentile(percentile_rank)
```

## Rationale

### Why Not Standard Deviation?

**Standard deviation is sensitive to outliers:**

```python
history = [50, 52, 51, 53, 200]  # 200 is a past event

# Standard deviation approach
mean = 101.2
std = 69.3  # Inflated by the outlier!
z_score = (60 - 101.2) / 69.3 = -0.595  # NORMAL (wrong!)

# MAD approach
median = 51.5
mad = 1.5
z_score = (60 - 51.5) / (1.4826 * 1.5) = 3.8  # HIGH (correct!)
```

**Why MAD is better:**
1. Uses median (robust to outliers)
2. Measures spread around median (not mean)
3. Breakdown point: 50% of data can be outliers
4. Constant factor (1.4826) normalizes to σ for Gaussian data

### MAD Calculation Example

**Baseline (August, 14:00 hour, Kolkata):**

```
Historical observations (365 days):
[48, 49, 50, 51, 51, 52, 52, 53, 54, 55, 56, 57, 58, 59, 60,
 61, 62, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74,
 ... (32 more values), ..., 200]  # One extreme event in past

Step 1: Sort
[48, 49, 50, ..., 200]

Step 2: Calculate median
median = 62 (middle value of 62 observations)

Step 3: Calculate absolute deviations
|48-62| = 14
|49-62| = 13
|50-62| = 12
...
|62-62| = 0
...
|200-62| = 138

Step 4: Median of absolute deviations
mad = 8.5 (median of deviation list)

Step 5: Normalize
constant = 1.4826
normalized_mad = 1.4826 * 8.5 = 12.6
```

### Severity Thresholds

```
Z-score = (observed - median) / (1.4826 * MAD)

NORMAL:     z < 2.0
LOW:        2.0 <= z < 3.0
HIGH:       3.0 <= z < 5.0
EXTREME:    z >= 5.0
```

**Interpretation (using example above):**

```
Scenario 1: Current = 65 µg/m³ (typical high)
z_score = (65 - 62) / 12.6 = 0.24
Severity: NORMAL ✓

Scenario 2: Current = 80 µg/m³ (pollution event starting)
z_score = (80 - 62) / 12.6 = 1.43
Severity: NORMAL (not yet a problem)

Scenario 3: Current = 100 µg/m³ (pollution spike)
z_score = (100 - 62) / 12.6 = 3.02
Severity: HIGH ⚠️

Scenario 4: Current = 150 µg/m³ (severe pollution)
z_score = (150 - 62) / 12.6 = 6.98
Severity: EXTREME 🔴
```

## Implementation

### PostgreSQL Schema

```sql
CREATE TABLE baselines (
    location_id VARCHAR(50),
    pollutant VARCHAR(20),
    hour_of_day INT,
    month INT,
    observation_count INT,
    median_value FLOAT,
    mad FLOAT,
    p25 FLOAT,
    p50 FLOAT,
    p75 FLOAT,
    p95 FLOAT,
    p99 FLOAT,
    UNIQUE(location_id, pollutant, hour_of_day, month)
);
```

### Anomaly Detection Code

```python
from src.aq_engine.analytics import AnomalyDetector

class AnomalyDetector:
    def __init__(self, db, storage):
        self.db = db
        self.storage = storage
    
    def detect(self, fact: HourlyFact) -> Anomaly:
        """Detect anomalies using MAD-based z-score."""
        
        # Load baseline for this (month, hour, location)
        baseline = self.db.get_baseline(
            location_id=fact.location_id,
            month=fact.hour_start.month,
            hour_of_day=fact.hour_start.hour
        )
        
        if baseline is None:
            # Insufficient historical data
            return Anomaly(
                severity="NORMAL",
                z_score=0.0,
                baseline_method="none"
            )
        
        # Check for zero MAD (all historical values identical)
        if baseline.mad == 0 or baseline.mad < 1e-6:
            return self._fallback_percentile(fact, baseline)
        
        # Calculate MAD-based z-score
        z_score = self._calculate_z_score(
            observed=fact.mean_value,
            baseline_median=baseline.median,
            baseline_mad=baseline.mad
        )
        
        # Classify severity
        severity = self._severity_from_z_score(z_score)
        
        return Anomaly(
            location_id=fact.location_id,
            hour_start=fact.hour_start,
            observed_value=fact.mean_value,
            baseline_median=baseline.median,
            z_score=z_score,
            severity=severity,
            baseline_method="mad"
        )
    
    def _calculate_z_score(self, observed, baseline_median, baseline_mad):
        """Calculate MAD-based z-score."""
        mad_normalized = 1.4826 * baseline_mad
        return (observed - baseline_median) / mad_normalized
    
    def _severity_from_z_score(self, z_score):
        """Convert z-score to severity level."""
        if z_score < 2.0:
            return "NORMAL"
        elif z_score < 3.0:
            return "LOW"
        elif z_score < 5.0:
            return "HIGH"
        else:
            return "EXTREME"
    
    def _fallback_percentile(self, fact, baseline):
        """Fallback when MAD = 0 (all historical values identical)."""
        
        # Fetch historical observations for this bucket
        history = self.storage.get_facts_for_bucket(
            location_id=fact.location_id,
            month=fact.hour_start.month,
            hour_of_day=fact.hour_start.hour,
            days=365
        )
        
        # Calculate percentile rank
        percentile_rank = sum(1 for h in history if h <= fact.mean_value) / len(history)
        
        if percentile_rank >= 0.95:
            severity = "EXTREME"
        elif percentile_rank >= 0.90:
            severity = "HIGH"
        elif percentile_rank >= 0.75:
            severity = "LOW"
        else:
            severity = "NORMAL"
        
        return Anomaly(
            severity=severity,
            baseline_method="percentile",
            percentile_rank=percentile_rank
        )
```

### Baseline Computation

```python
class BaselineComputer:
    def compute_baseline(self, location_id, days=365):
        """Compute 365-day baseline using MAD."""
        
        for month in range(1, 13):
            for hour in range(24):
                # Fetch all observations for this (month, hour)
                facts = self.storage.get_facts(
                    location_id=location_id,
                    month=month,
                    hour_of_day=hour,
                    days=days
                )
                
                if len(facts) < 5:
                    # Insufficient data
                    continue
                
                values = facts['mean_value'].to_list()
                
                # Calculate baseline statistics
                baseline = {
                    'median': np.percentile(values, 50),
                    'mad': np.median(np.abs(values - np.median(values))),
                    'p25': np.percentile(values, 25),
                    'p50': np.percentile(values, 50),
                    'p75': np.percentile(values, 75),
                    'p90': np.percentile(values, 90),
                    'p95': np.percentile(values, 95),
                    'p99': np.percentile(values, 99),
                    'observation_count': len(values)
                }
                
                # Store in PostgreSQL
                self.db.upsert_baseline(
                    location_id=location_id,
                    month=month,
                    hour_of_day=hour,
                    baseline=baseline
                )
```

## Test Coverage

**Example test case:** Zero MAD fallback

```python
def test_zero_mad_uses_percentile_fallback():
    """When MAD=0 (all historical values identical), use percentile rank."""
    
    # Historical data: all identical
    baseline = Baseline(
        median=55.0,
        mad=0.0,  # Zero MAD!
        p95=55.0
    )
    
    # Current observation above the flat historical line
    fact = HourlyFact(mean_value=65.0)
    
    # Should fall back to percentile
    anomaly = detector.detect(fact)
    
    assert anomaly.baseline_method == "percentile"
    assert anomaly.severity == "EXTREME"  # 100th percentile
```

## Performance

```
Baseline computation (365 days × 24 hours × 12 months):
- Load ~8,760 fact rows per location
- Calculate median: O(n log n) sort, O(1) lookup = ~1 ms
- Calculate MAD: O(n) deviations, O(n log n) sort = ~2 ms
- Total: ~24 * 12 * 3ms = ~1 second per location ✓

Anomaly detection (at inference time):
- Load baseline: O(1) index lookup = <1 ms
- Calculate z-score: O(1) = <0.1 ms
- Total per observation: <1.5 ms
```

## Tradeoffs

| Factor | MAD | Std Dev |
|--------|-----|---------|
| **Robustness to outliers** | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **Interpretability** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Computational cost** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Requires training** | ❌ | ❌ |
| **Works with sparse data** | ✅ | ⚠️ |

## Alternatives Considered

### 1. Simple Z-Score (Rejected)
```python
z_score = (current - mean) / std
```
**Problem:** One past event inflates std, making future events invisible

### 2. Isolation Forest (Rejected)
```python
from sklearn.ensemble import IsolationForest
model = IsolationForest().fit(history)
is_anomaly = model.predict([current]) == -1
```
**Problems:**
- Requires training → complexity
- Black-box → hard to explain to domain experts
- Overkill for univariate data

### 3. ARIMA/Exponential Smoothing (Rejected)
```python
from statsmodels.tsa.arima.model import ARIMA
model = ARIMA(history, order=(1,0,1)).fit()
forecast = model.get_forecast(steps=1)
residual = current - forecast.mean
```
**Problems:**
- Requires longer training windows
- Assumes stationarity (air quality is seasonal)
- More complex than needed

## Success Metrics

- ✅ **Precision:** < 5% false positive rate (domain experts accept alerts)
- ✅ **Recall:** > 90% of real pollution events detected
- ✅ **Latency:** Anomaly detection < 100 ms
- ✅ **Robustness:** Past extreme events don't inflate baseline

## Monitoring

```sql
-- Monitor baseline statistics
SELECT 
    location_id,
    COUNT(*) as baselines_count,
    AVG(mad) as avg_mad,
    MAX(mad) as max_mad,
    COUNT(*) FILTER (WHERE mad = 0) as zero_mad_count
FROM baselines
GROUP BY location_id;

-- Monitor anomaly distribution
SELECT 
    severity,
    COUNT(*) as count,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct
FROM anomalies
WHERE hour_start > now() - INTERVAL '7 days'
GROUP BY severity;
```

---

**Related:** [[001-postgresql-parquet-choice]], [[005-prediction-intervals]]
