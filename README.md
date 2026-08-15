# Air Quality Intelligence Platform

A local-first, open-source data engineering and analytics system for real-time air quality monitoring, anomaly detection, and near-term PM2.5 forecasting.

## Problem Statement

Current air-quality dashboards fail to distinguish normal seasonal and hourly variation from genuinely unusual pollution behavior, leaving operators unable to identify when an event requires attention. Raw sensor data from public sources contains duplicates, stale values, flatlines, and malformed records, yet existing systems often present this unreliable data directly to end users without meaningful validation or context. Air quality engineers need a trustworthy foundation that ingests, validates, and contextualizes observations so that alerts and forecasts reflect actual risk, not sensor noise.

The Air Quality Intelligence Platform solves this by implementing a rigorous data pipeline that continuously collects observations from OpenAQ and weather data from Open-Meteo, deduplicates and validates every record, computes historical baselines at the location and hour level, detects anomalies using robust statistical methods, identifies persistent pollution events, trains CPU-friendly time-series forecasting models, and exposes the results through an API and interactive dashboard—all on modest hardware (AMD Ryzen 3 / 16 GB RAM) using open-source tools and free public data.

## Architecture

### System Diagram

```
EXTERNAL SOURCES
    |
    +--→ OpenAQ (air quality)
    +--→ Open-Meteo (weather)
    |
    v
┌─────────────────────────────────┐
│   INGESTION SERVICES            │
│ (fetch, parse, validate, dedupe)│
└──────────┬──────────────────────┘
           |
           v
    ┌──────────────┐
    │  RAW LAYER   │
    │   (Parquet)  │
    └──────┬───────┘
           |
    ┌──────v────────────────────┐
    │  DATA QUALITY & VALIDATION │
    │ (Structural, semantic,     │
    │  temporal, referential)    │
    └──────┬──────────┬──────────┘
           |          |
           v          v
    ┌──────────┐  ┌──────────┐
    │  CLEAN   │  │QUARANTINE│
    │(Parquet) │  │          │
    └──────┬───┘  └──────────┘
           |
    ┌──────v──────────────────────────┐
    │ TRANSFORMATION LAYER             │
    │ (Polars / dbt)                   │
    └──────┬───────────┬───────────────┘
           |           |
           v           v
    ┌─────────────┐ ┌──────────┐
    │  ANALYTICAL │ │ FEATURES │
    │   MARTS     │ │  (for    │
    │  (hourly/   │ │   ML)    │
    │   daily)    │ └──┬───────┘
    └─────┬───────┘    |
          |            v
          |     ┌──────────────┐
          |     │ ML TRAINING  │
          |     │ & REGISTRY   │
          |     └──────┬───────┘
          |            |
          |            v
          |    ┌────────────────┐
          |    │ PREDICTIONS    │
          |    │ & INTERVALS    │
          |    └────────┬───────┘
          |             |
          +──────┬──────┘
                 v
    ┌────────────────────────┐
    │ CONTROL PLANE          │
    │ (PostgreSQL metadata,  │
    │ lineage, model registry)
    └────────────────────────┘
                 |
    ┌────────────v──────────────┐
    │  SERVING LAYER            │
    │  FastAPI (REST)           │
    │  Streamlit (Dashboard)    │
    └────────────────────────────┘
```

### Three-Plane Architecture

- **Data Plane**: Ingestion, raw storage, deduplication, quality validation and cleaning.
- **Intelligence Plane**: Analytics, anomaly detection, pollution events, baselines and forecasting.
- **Control Plane**: PostgreSQL metadata, pipeline state, lineage and model registry.

## Quick Start (5 Steps)

### 1. Prerequisites

- Docker & Docker Compose (v20.10+)
- Python 3.12+
- 8 GB RAM, 50 GB disk
- Git

### 2. Clone & Setup

```bash
git clone <repository>
cd air-quality-intelligence

# Copy environment file
cat > .env << 'EOF'
DATABASE_URL=postgresql://aq_user:aq_password@postgres:5432/air_quality
POSTGRES_USER=aq_user
POSTGRES_PASSWORD=aq_password
POSTGRES_DB=air_quality
API_HOST=0.0.0.0
API_PORT=8000
API_LOG_LEVEL=INFO
DATA_DIR=/data
PARQUET_PATH=/data/parquet
OPENAQ_API_KEY=your-key-here
AIRFLOW__WEBSERVER__SECRET_KEY=change-me-in-production
EOF
```

### 3. Launch Services

```bash
docker-compose up -d
sleep 30  # Wait for services to start

# Verify
docker-compose ps
```

Services:
- **PostgreSQL** (port 5432): Metadata, control plane, audit log
- **API** (port 8000): FastAPI with Pydantic validation
- **Airflow** (port 8080): Orchestration & DAGs

### 4. Initialize & Test

```bash
# Initialize database schema
docker-compose exec api python -m src.aq_engine.init_db

# Test API health
curl http://localhost:8000/api/system/health

# View Airflow DAGs
open http://localhost:8080  # admin / admin
```

### 5. Start Ingestion (Manual Trigger or Scheduled)

```bash
# Option A: Via Airflow UI (http://localhost:8080)
# Trigger "aq_hourly_ingest" DAG

# Option B: Via CLI
docker-compose exec api python -c "
from src.aq_engine.connectors import OpenAQConnector
from src.aq_engine.storage import ParquetStorage

storage = ParquetStorage('/data/parquet')
connector = OpenAQConnector()
records = connector.fetch()
storage.write(records)
"

# Verify data flow
curl http://localhost:8000/api/locations
```

**Result:** Hourly ingestion from OpenAQ & Open-Meteo, 1,200 + 450 records/hour

## API Usage Examples

### Get Current Observations

```bash
curl http://localhost:8000/api/locations/kolkata_001/current
```

**Response:**
```json
{
  "location_id": "kolkata_001",
  "pollutants": [{
    "pollutant": "PM2.5",
    "value": 65.5,
    "anomaly_severity": "HIGH",
    "baseline_median": 55.0
  }],
  "weather": {
    "temperature_c": 32.5,
    "humidity_pct": 75,
    "wind_speed_kmh": 12.0
  }
}
```

### Get Forecasts

```bash
curl "http://localhost:8000/api/locations/kolkata_001/forecast?horizon=1h,3h,6h"
```

**Response:**
```json
{
  "forecasts": [
    {
      "horizon_minutes": 60,
      "predicted_pm25": 62.0,
      "lower_bound": 55.0,
      "upper_bound": 70.0,
      "confidence": 0.85
    }
  ]
}
```

### Get Events (Pollution Spikes)

```bash
curl "http://localhost:8000/api/locations/kolkata_001/events?start_date=2026-08-14T00:00:00Z&end_date=2026-08-15T23:59:59Z"
```

### System Health

```bash
curl http://localhost:8000/api/system/health
```

See [API Specification](docs/05-api-specification.md) for full endpoint documentation.

## Project Structure

```
.
├── src/aq_engine/              # Main package
│   ├── __init__.py
│   ├── cli.py                  # Typer CLI
│   ├── config.py               # Configuration
│   ├── connectors/             # Data source connectors
│   ├── quality/                # Validation & quality
│   ├── analytics/              # Analytical layer
│   ├── ml/                     # Forecasting & ML
│   ├── api/                    # FastAPI application
│   └── dashboard/              # Streamlit app
├── dags/                       # Airflow DAGs
├── dbt/                        # dbt models & tests
├── sql/                        # SQL migrations & schemas
├── tests/                      # Test suite
├── configs/                    # Configuration files
├── data/                       # Data storage (local)
├── docker/                     # Docker & Compose configs
├── docs/                       # Documentation & ADRs
├── pyproject.toml              # Project metadata & deps
└── README.md
```

## Key Technologies

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Language | Python 3.12+ | Core implementation |
| Database | PostgreSQL | Metadata, control plane |
| Analytics | DuckDB | SQL over Parquet |
| Storage | Parquet | Immutable raw/clean/mart data |
| Processing | Polars | Memory-efficient transforms |
| Transforms | dbt Core | Reproducible SQL models |
| Orchestration | Airflow | DAGs, retries, backfills |
| ML | scikit-learn | Time-series forecasting |
| API | FastAPI | REST endpoints |
| Dashboard | Streamlit | Interactive analytics UI |
| Testing | pytest | Unit & integration tests |

## Data Sources

- **Air Quality**: [OpenAQ](https://docs.openaq.org/) — real-time observations from global monitoring networks
- **Weather**: [Open-Meteo](https://open-meteo.com/en/docs/) — temperature, humidity, wind, pressure, precipitation

## Development

### Running Tests

```bash
pytest tests/ -v --cov=src/aq_engine
```

### Linting & Type Checking

```bash
ruff check src/ tests/
mypy src/aq_engine --strict
```

### Code Style

Code is formatted with `black` and linted with `ruff`. All public APIs require type hints and docstrings.

## Documentation

Comprehensive documentation is in `docs/`:

### Core References
- **[01-system-architecture.md](docs/01-system-architecture.md)** — Three-plane architecture, technology stack, data flow, deployment model
- **[02-data-contracts.md](docs/02-data-contracts.md)** — Canonical schemas (air quality, weather, hourly facts, baselines, quality classifications)
- **[03-anomaly-detection-logic.md](docs/03-anomaly-detection-logic.md)** — MAD-based z-score, severity thresholds, fallback logic
- **[04-ml-specification.md](docs/04-ml-specification.md)** — 46 features, time-series splits, baselines, 4 ML candidates, 5% promotion criteria
- **[05-api-specification.md](docs/05-api-specification.md)** — 8 REST endpoints with JSON examples, error codes, rate limiting, client examples
- **[06-database-schema.md](docs/06-database-schema.md)** — DDL for 12 PostgreSQL tables, relationships, ER diagram, indexes, partitioning strategy
- **[07-deployment-guide.md](docs/07-deployment-guide.md)** — Docker Compose quick-start, env vars, K8s deployment, monitoring, troubleshooting
- **[08-runbook.md](docs/08-runbook.md)** — Manual backfill, model retraining, data recovery, disaster recovery procedures
- **[09-architecture-decisions/](docs/09-architecture-decisions/)** — ADRs:
  - `001-postgresql-parquet-choice.md` — Why dual storage (transactional DB + columnar files)
  - `004-anomaly-detection-mad.md` — Why Median Absolute Deviation (robust to outliers)

## Milestones

- **M0**: Foundation (repo, environment, config, logging)
- **M1**: Ingestion (connectors, raw storage, idempotency)
- **M2**: Quality (validation, quarantine, deduplication)
- **M3**: Analytics (hourly facts, baselines, station health)
- **M4**: Intelligence (anomaly detection, pollution events)
- **M5**: ML (models, training, registry, predictions)
- **M6**: Serving (API, dashboard)
- **M7**: Orchestration (Airflow, monitoring)
- **M8**: Hardening (tests, documentation, performance tuning)

## License

MIT

## Contact

For questions or contributions, open an issue or contact the Air Quality Engineering Team.
