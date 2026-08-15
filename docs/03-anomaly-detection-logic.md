# Air Quality Intelligence Platform: Anomaly Detection Logic

## Overview

Real-time anomaly detection identifies unusual air quality observations by comparing current measurements against robust historical baselines. The system uses Median Absolute Deviation (MAD) for outlier-resistant analysis.

## Z-Score Formula

### Standard Calculation

```
z_score = (observed_value - baseline_median) / (1.4826 × baseline_MAD)
```

### Components Explained

| Component | Definition | Example |
|-----------|-----------|---------|
| `observed_value` | Current measurement (µg/m³) | 80.0 |
| `baseline_median` | 365-day median for this (month, hour) | 55.0 |
| `baseline_mad` | Median Absolute Deviation | 8.5 |
| `1.4826` | Normalization constant (relates MAD to σ) | Fixed |
| `z_score` | Standardized distance from baseline | (80-55)/(1.4826×8.5) = 1.98 |

## Median Absolute Deviation (MAD)

### Definition

```
MAD = median(|history - median(history)|)
```

### Calculation Step-by-Step

**Given:** 62 historical observations for August, 14:00

```
Step 1: Sort observations
[48, 49, 50, 51, 52, ..., 70, 200]

Step 2: Calculate median
median = 62 (middle value)

Step 3: Calculate absolute deviations
|48 - 62| = 14
|49 - 62| = 13
|50 - 62| = 12
...
|62 - 62| = 0
...
|200 - 62| = 138

Step 4: Median of deviations
mad = 8.5 (median of deviation list)
```

### Why MAD?

**Robustness example:**

```
Scenario: One extreme event in past (200 µg/m³)

With Standard Deviation:
  mean = 61.2
  std = 18.3 (inflated by extreme)
  current=80 → z = (80-61.2)/18.3 = 1.03 → NORMAL (wrong!)

With MAD:
  median = 62.0
  mad = 8.5 (unaffected by extreme)
  current=80 → z = (80-62)/(1.4826×8.5) = 1.43 → LOW (correct!)
```

**Key advantage:** 50% of historical data can be outliers without affecting MAD

## Severity Thresholds

### Classification Rules

```
Z-Score Range   Severity   Color   Risk Level
─────────────────────────────────────────────
< 2.0          NORMAL     🟢      None
2.0 - 3.0      LOW        🟡      Moderate
3.0 - 5.0      HIGH       🟠      High
≥ 5.0          EXTREME    🔴      Critical
```

### Severity Interpretation

#### 1. NORMAL (z < 2.0)

**Meaning:** Within expected range for this hour/month

```
Baseline:  55 µg/m³ (median), MAD = 8.5
Threshold: 55 + (2 × 1.4826 × 8.5) = 80.2
Current:   75 µg/m³
Z-score:   1.18
Status:    ✓ NORMAL
```

**Action:** No alert

#### 2. LOW (2.0 ≤ z < 3.0)

**Meaning:** Moderately elevated, warrant monitoring

```
Current:   90 µg/m³
Z-score:   2.85
Status:    ⚠️ LOW
```

**Action:** Log, monitor, prepare for escalation

#### 3. HIGH (3.0 ≤ z < 5.0)

**Meaning:** Significant pollution event, notify operators

```
Current:   110 µg/m³
Z-score:   4.20
Status:    🟠 HIGH
```

**Action:** Alert operators, check for event merging (3+ consecutive HIGH)

#### 4. EXTREME (z ≥ 5.0)

**Meaning:** Severe pollution, health warnings

```
Current:   135 µg/m³
Z-score:   6.75
Status:    🔴 EXTREME
```

**Action:** Immediate alerts, issue public health warning

## Fallback Logic (Zero MAD)

### When Does MAD = 0?

All historical observations identical (rare but possible)

```
Historical: [55, 55, 55, 55, 55, 55, ..., 55]
Median:     55
Deviations: [0, 0, 0, 0, 0, 0, ..., 0]
MAD:        0 ← Can't divide by zero!
```

### Percentile Rank Fallback

When MAD = 0, use percentile-based classification:

```python
percentile_rank = (count of observations <= current) / total

if percentile_rank >= 0.95:
    severity = "EXTREME"     # Top 5%
elif percentile_rank >= 0.90:
    severity = "HIGH"        # Top 10%
elif percentile_rank >= 0.75:
    severity = "LOW"         # Top 25%
else:
    severity = "NORMAL"      # Bottom 75%
```

**Example:**

```
History: [55, 55, 55, 55, 55, ..., 55]  (all 62 values = 55)
Current: 65

Percentile rank: 62/62 = 100th percentile
→ EXTREME (outside historical range)
```

## Event Detection

### Anomaly-to-Event Mapping

**Single anomaly does NOT trigger an event.**

**Threshold:** 3+ HIGH/EXTREME anomalies in 4-hour window

```
08:00 → NORMAL
09:00 → HIGH     ← Count: 1
10:00 → HIGH     ← Count: 2
11:00 → HIGH     ← Count: 3 ← Event triggered! 🔴
12:00 → LOW
13:00 → HIGH
14:00 → HIGH
15:00 → HIGH
```

**Event created:** 09:00 - 15:00 (6 hours)

### Event Merging Rule

**Events ≤ 30 minutes apart merge into one event**

```
Event 1: 08:00 - 11:00 (HIGH/HIGH/HIGH)
Gap:     30 minutes (LOW at 11:30)
Event 2: 12:00 - 14:00 (HIGH/HIGH/HIGH)

→ Merged into: 08:00 - 14:00
```

**Rationale:** 30-min gap is atmospheric mixing, not separate events

## Quality Flag Assignment

### VALID Data

- All validation rules pass
- Confidence: 100%
- Used in all analytics

```python
is_valid = (
    is_not_null(value) and
    is_not_null(timestamp) and
    0 <= value <= 1000 and
    timestamp <= now + 1h and
    station_id in known_stations and
    not is_duplicate(measurement_key)
)
```

### SUSPICIOUS Data

- Present and potentially useful, but with warnings
- Requires investigation
- Used selectively

Examples:
```
- Duplicate (same measurement_key, <6h apart)
- Flatline (3+ identical consecutive values)
- Extreme outlier (z-score 4-6, historical)
- Future timestamp (> now, < 1h in future)
```

### INVALID Data

- Rejected, quarantined, never used
- Logged for debugging

Examples:
```
- Null required field (value, timestamp, location)
- Negative value (impossible)
- Station unknown (not in registry)
- Severely future timestamp (> now + 1h)
- Malformed JSON
```

## Implementation Example

### Python Code

```python
from src.aq_engine.analytics import AnomalyDetector

detector = AnomalyDetector(db=db, storage=storage)

# Current hourly fact
fact = {
    'location_id': 'kolkata_001',
    'hour_start': '2026-08-15T14:00:00Z',
    'mean_value': 95.0
}

# Detect anomaly
anomaly = detector.detect(fact)

print(f"Z-Score: {anomaly.z_score:.2f}")
print(f"Severity: {anomaly.severity}")
print(f"Baseline: {anomaly.baseline_median} µg/m³")
print(f"MAD: {anomaly.baseline_mad}")

# Output:
# Z-Score: 2.85
# Severity: LOW
# Baseline: 62 µg/m³
# MAD: 8.5
```

### SQL Queries

**Find recent HIGH/EXTREME anomalies:**

```sql
SELECT 
    a.location_id,
    a.hour_start,
    a.observed_value,
    a.z_score,
    a.severity
FROM anomalies a
WHERE 
    a.location_id = 'kolkata_001'
    AND a.hour_start > now() - interval '24 hours'
    AND a.severity IN ('HIGH', 'EXTREME')
ORDER BY a.hour_start DESC;
```

**Find events triggered by anomalies:**

```sql
SELECT 
    e.event_id,
    e.start_time,
    e.end_time,
    e.peak_value,
    e.severity,
    COUNT(a.anomaly_id) as anomaly_count
FROM events e
LEFT JOIN anomalies a 
    ON e.location_id = a.location_id
    AND a.hour_start BETWEEN e.start_time AND e.end_time
WHERE e.location_id = 'kolkata_001'
GROUP BY e.event_id
ORDER BY e.start_time DESC;
```

## Testing & Validation

### Unit Test Examples

```python
def test_z_score_calculation():
    """Verify z-score formula."""
    baseline_median = 55.0
    baseline_mad = 8.5
    current = 95.0
    
    z_score = (current - baseline_median) / (1.4826 * baseline_mad)
    
    assert abs(z_score - 3.36) < 0.01  # ≈3.36
    assert get_severity(z_score) == "HIGH"

def test_zero_mad_fallback():
    """When MAD=0, use percentile rank."""
    history = [55, 55, 55, 55, 55]  # All identical
    current = 70
    
    percentile = (sum(1 for h in history if h <= current)) / len(history)
    assert percentile == 1.0  # 100th percentile
    assert get_severity_from_percentile(percentile) == "EXTREME"

def test_event_merging():
    """Events <= 30min apart merge."""
    event1 = Event(start='08:00', end='11:00')
    event2 = Event(start='11:30', end='14:00')  # 30min gap
    
    merged = merge_events([event1, event2])
    
    assert len(merged) == 1
    assert merged[0].start == '08:00'
    assert merged[0].end == '14:00'
```

## Performance Considerations

### Computational Cost

**Per-observation anomaly detection:**
- Load baseline: O(1) index lookup = <1 ms
- Calculate z-score: O(1) = <0.1 ms
- **Total: <1.5 ms per observation**

**For 1,200 observations/hour:**
- Total time: 1,200 × 1.5 ms = 1.8 seconds
- Batching: Process all observations in parallel = <1 second

### Storage

**Anomaly table:**
- ~24 rows/location/day (1 per hour, only if detected)
- 30 locations → 720 rows/day
- 365 days → 262,800 rows
- Space: ~50 MB (very small, easily indexed)

## Monitoring & Alerts

### Key Metrics

```sql
-- Anomaly distribution
SELECT 
    severity,
    COUNT(*) as count,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct
FROM anomalies
WHERE hour_start > now() - interval '7 days'
GROUP BY severity;

-- Expected: ~90% NORMAL, ~8% LOW, ~1.9% HIGH, ~0.1% EXTREME

-- Baseline stats
SELECT 
    location_id,
    COUNT(*) as baseline_count,
    AVG(mad) as avg_mad,
    MIN(mad) as min_mad
FROM baselines
GROUP BY location_id;
```

### Alert Conditions

| Condition | Threshold | Action |
|-----------|-----------|--------|
| EXTREME anomalies | > 5/day | Investigate sensor calibration |
| Zero MAD | > 10% of baselines | Check data quality, historical flatlines |
| Missing observations | > 1h gap | Alert on missing data |
| Baseline age | > 1 month old | Recompute baselines |

---

**Next:** See [ML Specification](04-ml-specification.md) for forecasting details.
