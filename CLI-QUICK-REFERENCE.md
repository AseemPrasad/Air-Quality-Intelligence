# CLI Quick Reference

## Installation

```bash
cd air-quality-intelligence
pip install -e ".[dev]"
```

## All Commands

### Data Ingestion
```bash
aq ingest --source openaq [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
aq ingest --source weather [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
```

### Data Quality
```bash
aq validate --date YYYY-MM-DD
aq aggregate --date YYYY-MM-DD
```

### Analytics
```bash
aq detect-anomalies --date YYYY-MM-DD
aq detect-events --date YYYY-MM-DD
```

### Machine Learning
```bash
aq train --target {pm25_1h|pm25_3h|pm25_6h}
aq predict --horizon {1h|3h|6h}
```

### Operations
```bash
aq backfill --source {openaq|weather} --start YYYY-MM-DD --end YYYY-MM-DD
aq health
aq api [--port 8000] [--host 0.0.0.0]
aq dashboard [--port 8501]
```

## Global Options (All Commands)

```bash
--config-dir PATH           # Configuration directory (default: ./configs)
--log-level {DEBUG|INFO|WARNING|ERROR}  # Log level
--help                      # Show command help
```

## Configuration

### Files
- `configs/default.yaml` — Main configuration
- `configs/logging.yaml` — Logging setup

### Environment Variables (Override YAML)
```bash
# Database
DATABASE_URL=postgresql://...
POSTGRES_USER=...
POSTGRES_PASSWORD=...

# API
API_HOST=0.0.0.0
API_PORT=8000

# External APIs
OPENAQ_API_KEY=...

# ML
ENABLE_ML_TRAINING=true
MODEL_PROMOTION_THRESHOLD=0.05
```

## Exit Codes
- **0** — Success
- **1** — Error

## Output Format
All output is JSON:
```json
{
  "status": "success|error",
  "timestamp": "ISO 8601",
  "...": "command-specific data"
}
```

## Logging
- Console: JSON-formatted to stdout
- File: `./data/logs/aq_engine.log` (debug level)
- Errors: `./data/logs/aq_engine_error.log`

## Examples

### Single Day Pipeline
```bash
aq ingest --source openaq --start-date 2026-08-15 --end-date 2026-08-15
aq validate --date 2026-08-15
aq aggregate --date 2026-08-15
aq detect-anomalies --date 2026-08-15
aq detect-events --date 2026-08-15
aq predict --horizon 1h
```

### Weekly Training
```bash
aq train --target pm25_1h
aq train --target pm25_3h
aq train --target pm25_6h
```

### System Check
```bash
aq health
```

### Start Services
```bash
aq api --port 8000
aq dashboard --port 8501
```

## Troubleshooting

### Config Not Found
```bash
aq ingest --source openaq --config-dir ./configs
```

### View Debug Logs
```bash
aq ingest --source openaq --log-level DEBUG
```

### Check What's Wrong
```bash
aq health
```

---

See [CLI-and-Configuration.md](docs/CLI-and-Configuration.md) for full documentation.
