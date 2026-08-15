# CLI and Configuration System

## Overview

The Air Quality Intelligence Platform provides a comprehensive command-line interface (CLI) using Typer and a flexible configuration system supporting YAML files with environment variable overrides.

## Installation

### Dependencies

Add to `pyproject.toml`:

```toml
[project]
dependencies = [
    "typer[all]==0.12.0",
    "pydantic==2.5.0",
    "pyyaml==6.0.1",
    "python-json-logger==2.0.7",
    "uvicorn==0.24.0",
    "fastapi==0.104.0",
    "streamlit==1.28.0",
    "rich==13.7.0",
]
```

### Install

```bash
pip install -e ".[dev]"
```

## Configuration System

### File Structure

```
configs/
├── default.yaml       # Default configuration
└── logging.yaml       # Logging configuration
```

### Configuration Files

#### configs/default.yaml

```yaml
database:
  url: postgresql://user:pass@localhost/db
  user: aq_user
  password: aq_password
  host: localhost
  port: 5432
  database: air_quality
  pool_size: 10
  max_overflow: 20

data:
  parquet_path: ./data/parquet
  checkpoint_path: ./data/checkpoints
  log_path: ./data/logs

api:
  host: 0.0.0.0
  port: 8000
  workers: 4
  timeout_seconds: 30

connectors:
  openaq_api_key: ""
  openaq_api_url: https://api.openaq.org/v2
  openmeteo_api_url: https://api.open-meteo.com/v1

airflow:
  home: /opt/airflow
  dags_folder: /opt/airflow/dags

ml:
  enable_training: true
  enable_inference: true
  training_days: 90
  promotion_threshold: 0.05

analytics:
  baseline_days: 365
  anomaly_z_threshold_low: 2.0
  anomaly_z_threshold_high: 3.0
  anomaly_z_threshold_extreme: 5.0
```

### Configuration Loading

Configuration is loaded in this order (later overrides earlier):

1. **Default config file** (`configs/default.yaml`)
2. **Environment variables** (highest priority)

### Environment Variables

All configuration can be overridden via environment variables:

#### Database

```bash
DATABASE_URL=postgresql://user:pass@host:5432/db
POSTGRES_USER=aq_user
POSTGRES_PASSWORD=aq_password
DATABASE_HOST=localhost
DATABASE_PORT=5432
POSTGRES_DB=air_quality
```

#### Data

```bash
PARQUET_PATH=/data/parquet
CHECKPOINT_PATH=/data/checkpoints
LOG_PATH=/data/logs
```

#### API

```bash
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_LOG_LEVEL=INFO
```

#### Connectors

```bash
OPENAQ_API_KEY=your-api-key
OPENAQ_API_URL=https://api.openaq.org/v2
OPENMETEO_API_URL=https://api.open-meteo.com/v1
```

#### Airflow

```bash
AIRFLOW_HOME=/opt/airflow
AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags
```

#### ML

```bash
ENABLE_ML_TRAINING=true
ENABLE_ML_INFERENCE=true
MODEL_PROMOTION_THRESHOLD=0.05
```

#### Analytics

```bash
BASELINE_DAYS=365
EVENT_MERGE_GAP_MINUTES=30
```

## CLI Commands

All commands support:

```bash
aq <command> --help                    # Show command help
aq <command> --config-dir ./configs    # Override config directory
aq <command> --log-level DEBUG|INFO    # Override log level
```

### 1. Data Ingestion

**Ingest air quality data:**

```bash
aq ingest --source openaq
aq ingest --source openaq --start-date 2026-08-14 --end-date 2026-08-15
```

**Ingest weather data:**

```bash
aq ingest --source weather
aq ingest --source weather --start-date 2026-08-01 --end-date 2026-08-31
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "source": "openaq",
  "records_ingested": 1200,
  "start_date": "2026-08-15",
  "end_date": "2026-08-15"
}
```

### 2. Data Validation

**Validate raw data:**

```bash
aq validate --date 2026-08-15
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "date": "2026-08-15",
  "valid": 2580,
  "suspicious": 45,
  "invalid": 25,
  "total": 2650
}
```

### 3. Hourly Aggregation

**Compute hourly facts:**

```bash
aq aggregate --date 2026-08-15
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "date": "2026-08-15",
  "hourly_facts_created": 48
}
```

### 4. Anomaly Detection

**Detect anomalies:**

```bash
aq detect-anomalies --date 2026-08-15
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "date": "2026-08-15",
  "anomalies_detected": 12
}
```

### 5. Event Detection

**Detect pollution events:**

```bash
aq detect-events --date 2026-08-15
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "date": "2026-08-15",
  "events_detected": 2
}
```

### 6. Model Training

**Train forecasting models:**

```bash
aq train --target pm25_1h
aq train --target pm25_3h
aq train --target pm25_6h
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "target": "pm25_1h",
  "model_id": "2026-08-15_hgb",
  "metrics": {
    "mae": 12.3,
    "rmse": 15.8,
    "mape": 0.18
  }
}
```

### 7. Predictions

**Generate forecasts:**

```bash
aq predict --horizon 1h
aq predict --horizon 3h
aq predict --horizon 6h
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "horizon": "1h",
  "predictions_generated": 24
}
```

### 8. Historical Backfill

**Backfill historical data:**

```bash
aq backfill --source openaq --start 2026-08-01 --end 2026-08-15
aq backfill --source weather --start 2026-08-01 --end 2026-08-15
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "source": "openaq",
  "start_date": "2026-08-01",
  "end_date": "2026-08-15",
  "records_backfilled": 18000
}
```

### 9. System Health

**Check system health:**

```bash
aq health
```

**Output:**
```json
{
  "status": "success",
  "timestamp": "2026-08-15T10:30:00.000000",
  "database": "ok",
  "storage": "ok",
  "overall": "ok"
}
```

### 10. API Server

**Start API server:**

```bash
aq api
aq api --port 9000 --host 127.0.0.1
```

**Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 11. Dashboard

**Start Streamlit dashboard:**

```bash
aq dashboard
aq dashboard --port 8502
```

## Logging

### Configuration

Logging is configured in `configs/logging.yaml`:

- **Console output:** JSON-formatted logs to stdout
- **File output:** Debug-level logs to `./data/logs/aq_engine.log`
- **Error file:** Error-level logs to `./data/logs/aq_engine_error.log`

### Log Structure

Each log entry is JSON with fields:

```json
{
  "timestamp": "2026-08-15T10:30:00.000000",
  "level": "INFO",
  "name": "src.aq_engine.ingestion",
  "operation": "ingest",
  "source": "openaq",
  "status": "success",
  "message": "Ingestion completed: 1200 records"
}
```

### Structured Logging

All CLI commands include structured context:

```python
logger.info(
    "Operation message",
    extra={
        "operation": "ingest",
        "source": "openaq",
        "status": "success",
        "record_count": 1200
    }
)
```

## Error Handling

### Exit Codes

- **0:** Success
- **1:** Error

### Error Output

All errors return JSON:

```json
{
  "status": "error",
  "timestamp": "2026-08-15T10:30:00.000000",
  "error": "Configuration error: database.url is required"
}
```

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Configuration not found` | Missing `configs/default.yaml` | Create file or set `--config-dir` |
| `Database connection failed` | Invalid DATABASE_URL or PostgreSQL down | Check env vars, verify PostgreSQL |
| `Parquet path not accessible` | Invalid PARQUET_PATH or permissions | Check path and permissions |
| `API key missing` | OPENAQ_API_KEY not set | Set environment variable |

## Examples

### Daily Workflow

```bash
# 1. Ingest new data
aq ingest --source openaq --start-date 2026-08-15 --end-date 2026-08-15
aq ingest --source weather --start-date 2026-08-15 --end-date 2026-08-15

# 2. Validate
aq validate --date 2026-08-15

# 3. Aggregate
aq aggregate --date 2026-08-15

# 4. Detect anomalies
aq detect-anomalies --date 2026-08-15

# 5. Detect events
aq detect-events --date 2026-08-15

# 6. Generate predictions
aq predict --horizon 1h

# 7. Check health
aq health
```

### Historical Backfill

```bash
# Backfill August 2026
aq backfill --source openaq --start 2026-08-01 --end 2026-08-31
aq backfill --source weather --start 2026-08-01 --end 2026-08-31

# Then validate and aggregate all days
for day in {01..31}; do
  aq validate --date "2026-08-$day"
  aq aggregate --date "2026-08-$day"
done
```

### Weekly Training

```bash
# Train models every Sunday
aq train --target pm25_1h
aq train --target pm25_3h
aq train --target pm25_6h

# Check new model performance
aq health
```

## Testing

Run CLI tests:

```bash
pytest tests/unit/test_cli.py -v
```

Test coverage:

- ✅ All commands load without error
- ✅ Help text (--help) works for all commands
- ✅ Configuration loading and validation
- ✅ Environment variable overrides
- ✅ JSON output format
- ✅ Error handling and exit codes
- ✅ Logging setup

---

**Related:** [System Architecture](01-system-architecture.md), [Deployment Guide](07-deployment-guide.md)
