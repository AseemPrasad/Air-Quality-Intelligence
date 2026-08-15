# Air Quality Intelligence Platform: Database Schema

## Overview

PostgreSQL serves as the control plane for the Air Quality Intelligence Platform. It stores metadata, model registry, watermarks, and audit logs. Immutable analytics data is stored in Parquet files.

**Key principles:**
- ACID guarantees for critical operations
- Watermarks for idempotent re-running
- Audit columns (created_at, updated_at) on all tables
- Foreign key relationships
- Indexes on query paths

## Tables

### 1. `locations`

Monitor locations (Kolkata, Delhi, etc.)

```sql
CREATE TABLE locations (
    location_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    timezone VARCHAR(50) NOT NULL,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_locations_city ON locations(city);
CREATE INDEX idx_locations_active ON locations(active);
```

### 2. `stations`

Physical monitoring stations within locations

```sql
CREATE TABLE stations (
    station_id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(50) NOT NULL REFERENCES locations(location_id),
    external_id VARCHAR(255) NOT NULL UNIQUE,
    source VARCHAR(50) NOT NULL,  -- 'openaq', 'openmeteo', etc.
    name VARCHAR(255),
    latitude FLOAT,
    longitude FLOAT,
    elevation_m FLOAT,
    active BOOLEAN DEFAULT true,
    first_data_time TIMESTAMP,
    last_data_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_stations_location ON stations(location_id);
CREATE INDEX idx_stations_source ON stations(source);
CREATE INDEX idx_stations_external_id ON stations(external_id);
```

### 3. `watermarks`

Ingestion checkpoints (idempotency)

```sql
CREATE TABLE watermarks (
    watermark_id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,  -- 'openaq', 'open_meteo'
    location_id VARCHAR(50) NOT NULL,
    last_processed_time TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'success', 'failed'
    error_message TEXT,
    record_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, location_id)
);

CREATE INDEX idx_watermarks_source_location ON watermarks(source, location_id);
CREATE INDEX idx_watermarks_status ON watermarks(status);
```

### 4. `hourly_facts`

Aggregated observations (1 row/location/hour)

```sql
CREATE TABLE hourly_facts (
    fact_id BIGSERIAL PRIMARY KEY,
    location_id VARCHAR(50) NOT NULL REFERENCES locations(location_id),
    hour_start TIMESTAMP NOT NULL,
    hour_end TIMESTAMP NOT NULL,
    pollutant VARCHAR(20) NOT NULL DEFAULT 'PM2.5',
    mean_value FLOAT NOT NULL,
    median_value FLOAT NOT NULL,
    min_value FLOAT NOT NULL,
    max_value FLOAT NOT NULL,
    stddev_value FLOAT,
    observation_count INT NOT NULL,
    coverage_pct FLOAT NOT NULL,
    data_quality_flag VARCHAR(20),  -- 'VALID', 'SUSPICIOUS', 'INVALID'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, hour_start, pollutant)
);

CREATE INDEX idx_hourly_facts_location_time ON hourly_facts(location_id, hour_start DESC);
CREATE INDEX idx_hourly_facts_pollutant ON hourly_facts(pollutant);
CREATE INDEX idx_hourly_facts_hour_start ON hourly_facts(hour_start DESC);
```

### 5. `baselines`

365-day baseline statistics (hour + month specific)

```sql
CREATE TABLE baselines (
    baseline_id SERIAL PRIMARY KEY,
    location_id VARCHAR(50) NOT NULL REFERENCES locations(location_id),
    pollutant VARCHAR(20) NOT NULL DEFAULT 'PM2.5',
    hour_of_day INT NOT NULL,  -- 0-23
    month INT NOT NULL,  -- 1-12
    observation_count INT NOT NULL,
    median_value FLOAT NOT NULL,
    mad FLOAT NOT NULL,  -- Median Absolute Deviation
    p25 FLOAT,
    p50 FLOAT,
    p75 FLOAT,
    p90 FLOAT,
    p95 FLOAT,
    p99 FLOAT,
    last_computed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, pollutant, hour_of_day, month)
);

CREATE INDEX idx_baselines_location_time ON baselines(location_id, hour_of_day, month);
```

### 6. `anomalies`

Detected anomalies (hourly)

```sql
CREATE TABLE anomalies (
    anomaly_id BIGSERIAL PRIMARY KEY,
    location_id VARCHAR(50) NOT NULL REFERENCES locations(location_id),
    hour_start TIMESTAMP NOT NULL,
    pollutant VARCHAR(20) NOT NULL DEFAULT 'PM2.5',
    observed_value FLOAT NOT NULL,
    baseline_median FLOAT NOT NULL,
    z_score FLOAT NOT NULL,
    severity VARCHAR(20) NOT NULL,  -- 'NORMAL', 'LOW', 'HIGH', 'EXTREME'
    baseline_method VARCHAR(50),  -- 'mad', 'percentile'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, hour_start, pollutant)
);

CREATE INDEX idx_anomalies_location_time ON anomalies(location_id, hour_start DESC);
CREATE INDEX idx_anomalies_severity ON anomalies(severity);
```

### 7. `events`

Detected pollution events

```sql
CREATE TABLE events (
    event_id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(50) NOT NULL REFERENCES locations(location_id),
    pollutant VARCHAR(20) NOT NULL DEFAULT 'PM2.5',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_hours FLOAT,
    peak_value FLOAT NOT NULL,
    mean_value FLOAT NOT NULL,
    peak_anomaly_score FLOAT NOT NULL,
    baseline_median FLOAT,
    severity VARCHAR(20) NOT NULL,  -- 'MILD', 'MODERATE', 'SEVERE'
    anomaly_count INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_location_time ON events(location_id, start_time DESC);
CREATE INDEX idx_events_severity ON events(severity);
CREATE INDEX idx_events_period ON events(start_time, end_time);
```

### 8. `models`

ML model registry

```sql
CREATE TABLE models (
    model_id VARCHAR(50) PRIMARY KEY,
    model_name VARCHAR(255) NOT NULL,  -- 'linear', 'random_forest', 'xgboost', etc.
    model_type VARCHAR(50) NOT NULL,  -- 'baseline', 'ml'
    version VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'candidate',  -- 'candidate', 'production', 'archived'
    trained_at TIMESTAMP,
    training_days INT,  -- 90, 365, etc.
    train_size INT,
    validation_size INT,
    test_size INT,
    mae FLOAT,
    rmse FLOAT,
    mape FLOAT,
    file_path VARCHAR(500) NOT NULL,
    artifact_hash VARCHAR(64),
    metadata_json JSONB,
    promoted_at TIMESTAMP,
    archived_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_models_status ON models(status);
CREATE INDEX idx_models_trained_at ON models(trained_at DESC);
CREATE UNIQUE INDEX idx_models_production ON models((status))
    WHERE status = 'production';
```

### 9. `predictions`

Inference results (forecast points)

```sql
CREATE TABLE predictions (
    prediction_id BIGSERIAL PRIMARY KEY,
    model_id VARCHAR(50) NOT NULL REFERENCES models(model_id),
    location_id VARCHAR(50) NOT NULL REFERENCES locations(location_id),
    reference_time TIMESTAMP NOT NULL,
    target_time TIMESTAMP NOT NULL,
    horizon_minutes INT NOT NULL,
    predicted_value FLOAT NOT NULL,
    lower_bound FLOAT,
    upper_bound FLOAT,
    confidence FLOAT,  -- 0-1
    actual_value FLOAT,
    error FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_predictions_location_time ON predictions(location_id, target_time DESC);
CREATE INDEX idx_predictions_model ON predictions(model_id);
CREATE INDEX idx_predictions_horizon ON predictions(horizon_minutes);
```

### 10. `data_quality_log`

Data quality tracking

```sql
CREATE TABLE data_quality_log (
    log_id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    total_records INT NOT NULL,
    valid_records INT NOT NULL,
    suspicious_records INT NOT NULL,
    invalid_records INT NOT NULL,
    duplicate_records INT NOT NULL,
    coverage_pct FLOAT,
    validation_rules_failed JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_data_quality_log_period ON data_quality_log(period_start DESC);
CREATE INDEX idx_data_quality_log_source ON data_quality_log(source);
```

### 11. `ingestion_log`

Detailed ingestion tracking

```sql
CREATE TABLE ingestion_log (
    log_id BIGSERIAL PRIMARY KEY,
    dag_run_id VARCHAR(255) NOT NULL,
    task_name VARCHAR(100) NOT NULL,
    source VARCHAR(50),
    status VARCHAR(20) NOT NULL,  -- 'pending', 'running', 'success', 'failed'
    records_processed INT,
    records_failed INT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds INT,
    error_message TEXT,
    metadata_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ingestion_log_dag ON ingestion_log(dag_run_id);
CREATE INDEX idx_ingestion_log_status ON ingestion_log(status);
```

### 12. `feature_cache`

Cached feature vectors (for training efficiency)

```sql
CREATE TABLE feature_cache (
    cache_id BIGSERIAL PRIMARY KEY,
    reference_time TIMESTAMP NOT NULL,
    location_id VARCHAR(50) NOT NULL,
    features_json JSONB NOT NULL,  -- 46 features
    feature_count INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(reference_time, location_id)
);

CREATE INDEX idx_feature_cache_time ON feature_cache(reference_time DESC);
```

## ER Diagram

```
┌─────────────────┐
│  locations      │
├─────────────────┤
│ location_id (PK)│
│ name            │
│ city            │
│ latitude        │
│ longitude       │
└────────┬────────┘
         │ 1
         │ owns many
         │ M
    ┌────▼────────────┐
    │  stations       │
    ├─────────────────┤
    │ station_id (PK) │
    │ location_id (FK)│
    │ external_id     │
    │ source          │
    └─────────────────┘

┌─────────────────┐
│  watermarks     │
├─────────────────┤
│ watermark_id(PK)│
│ source          │
│ location_id     │
│ last_processed  │
└─────────────────┘

┌──────────────────┐
│  hourly_facts    │      ┌─────────────┐
├──────────────────┤      │  baselines  │
│ fact_id (PK)     │      ├─────────────┤
│ location_id (FK) │◄────►│ location_id │
│ hour_start       │      │ hour_of_day │
│ mean_value       │      │ month       │
│ median_value     │      │ median      │
└──────────────────┘      │ mad         │
         │                 └─────────────┘
         │ detects
         │ anomalies
         │
    ┌────▼─────────────┐
    │  anomalies      │
    ├─────────────────┤
    │ anomaly_id (PK) │
    │ location_id (FK)│
    │ hour_start      │
    │ z_score         │
    │ severity        │
    └────┬────────────┘
         │ triggers
         │ events
         │
    ┌────▼─────────┐
    │  events      │
    ├──────────────┤
    │ event_id(PK) │
    │ location_id  │
    │ start_time   │
    │ end_time     │
    │ severity     │
    └──────────────┘

┌──────────────────┐      ┌────────────────┐
│  models          │      │  predictions   │
├──────────────────┤      ├────────────────┤
│ model_id (PK)    │◄─┬───┤ prediction_id  │
│ model_name       │  │   │ model_id (FK)  │
│ status           │  │   │ location_id    │
│ mae              │  │   │ target_time    │
│ file_path        │  │   │ predicted_val  │
└──────────────────┘  │   └────────────────┘
                      │
                      └───(1 model produces
                            many predictions)
```

## Key Relationships

| From | To | Relationship | Cardinality |
|------|-----|------------|---|
| locations | stations | owns | 1:M |
| locations | hourly_facts | has | 1:M |
| locations | anomalies | has | 1:M |
| locations | events | has | 1:M |
| locations | predictions | has | 1:M |
| hourly_facts | anomalies | triggers | 1:M |
| anomalies | events | merges into | M:1 |
| models | predictions | generates | 1:M |

## Indexing Strategy

**Query Paths (most frequent):**

1. **Time-series queries** (e.g., "last 7 days for location")
   - Index: `idx_hourly_facts_location_time`
   - Query: `WHERE location_id = ? AND hour_start > ? ORDER BY hour_start DESC`

2. **Recent anomalies** (e.g., "HIGH/EXTREME in last 24h")
   - Index: `idx_anomalies_severity`, `idx_anomalies_location_time`
   - Query: `WHERE location_id = ? AND hour_start > ? AND severity IN (...)`

3. **Event queries** (e.g., "events in date range")
   - Index: `idx_events_period`, `idx_events_location_time`
   - Query: `WHERE location_id = ? AND start_time >= ? AND end_time <= ?`

4. **Baseline lookups** (e.g., "baseline for 14:00 in August")
   - Index: `idx_baselines_location_time`
   - Query: `WHERE location_id = ? AND hour_of_day = ? AND month = ?`

5. **Model registry** (e.g., "current production model")
   - Index: `idx_models_production`
   - Query: `WHERE status = 'production' LIMIT 1`

## Partitioning Strategy

**Recommendation:** Partition `hourly_facts` by month for operational efficiency.

```sql
-- Partition by month (automated via retention policy)
-- Older than 24 months: archive to cold storage
-- 12-24 months: read-only
-- < 12 months: read-write
```

## Audit Columns

All tables include:
- `created_at`: Row creation timestamp
- `updated_at`: Last modification timestamp

These enable:
- Change tracking
- Audit trails
- Data governance

## Connection Pooling

**Recommended settings:**

```yaml
pool_size: 10
max_overflow: 20
pool_recycle: 3600
pool_pre_ping: true
echo: false
```

## Backup & Recovery

**Daily backups:**
- Full backup: Daily at 02:00 UTC
- WAL archiving: Every 5 minutes
- Recovery time objective (RTO): 1 hour
- Recovery point objective (RPO): 5 minutes

## Monitoring Queries

**Table sizes:**
```sql
SELECT 
    schemaname, tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

**Index usage:**
```sql
SELECT 
    schemaname, tablename, indexname,
    idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

**Slow queries:**
```sql
SELECT 
    query, calls, total_time, mean_time
FROM pg_stat_statements
WHERE mean_time > 100  -- > 100ms
ORDER BY mean_time DESC;
```

---

**Next:** See [Deployment Guide](07-deployment-guide.md) for PostgreSQL setup.
