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

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12+
- Git

### Launch

```bash
docker-compose up -d
```

This brings up:
- **PostgreSQL** (metadata/control plane)
- **Airflow** (orchestration)
- **Python** services (ingestion, validation, ML)

### Environment Setup

```bash
# Clone and navigate to the project
git clone <repository>
cd air-quality-intelligence

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Verify installation
aq health
```

## CLI Usage

### Core Commands

```bash
# Ingest data from sources
aq ingest --source openaq
aq ingest --source weather

# Validate raw data for a specific date
aq validate --date 2026-08-15

# Compute hourly aggregates
aq aggregate --date 2026-08-15

# Detect anomalies and pollution events
aq detect-anomalies --date 2026-08-15
aq detect-events --date 2026-08-15

# Train forecasting models
aq train --target pm25_1h

# Generate predictions
aq predict --horizon 1h

# Backfill historical data
aq backfill --source openaq --start 2026-01-01 --end 2026-01-07

# Check system health
aq health
```

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

- `01-product-requirements.md` — Problem, scope, non-functional requirements
- `02-system-architecture.md` — Design, principles, patterns
- `03-data-architecture.md` — Storage layout, partitioning strategy
- `04-data-contracts.md` — Canonical schemas and interfaces
- `05-database-design.md` — PostgreSQL schema, relationships
- `06-data-quality.md` — Validation rules, quality classes
- `07-pipeline-design.md` — Ingestion, orchestration, failure handling
- `08-analytics-specification.md` — Baselines, aggregation, coverage
- `09-ml-specification.md` — Features, models, evaluation, promotion
- `10-api-specification.md` — Endpoints, response schemas
- `11-dashboard-specification.md` — Pages, visualizations, interactions
- `12-testing-strategy.md` — Coverage, CI/CD
- `13-observability.md` — Logging, lineage, monitoring
- `18-architecture-decisions/` — ADRs for major choices

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
