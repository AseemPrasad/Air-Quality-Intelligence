# Master Repository Analysis: Air Quality Intelligence Engine

---

## 1. Executive Summary

The **Air Quality Intelligence Engine (`aq_engine`)** is an end-to-end data platform and predictive modeling system designed to ingest, validate, standardize, analyze, and forecast urban air quality and meteorological data.

### Core Capabilities

* **Multi-Source Ingestion:** Connects to external REST APIs (OpenAQ for pollutants and Open-Meteo for weather/atmospheric features) with rate limiting, retry backoff, and pagination.
* **Data Quality & Governance Control Plane:** Implements strict data contract validation, deduplication via cryptographic content hashing (SHA-256), late-arrival tracking, and data quarantine pipelines.
* **Dual-Tier Hybrid Storage:** Utilizes a PostgreSQL relational control plane (for station metadata, ingestion runs, validation audit logs, and anomaly events) paired with a partitioned Apache Parquet data lakehouse layer (for time-series analytical facts).
* **Analytics & Statistical Anomaly Detection:** Features rolling multi-scale aggregations (1h, 24h, 7d, 30d), station sensor health scorecards (drift, flatline, coverage), Median Absolute Deviation (MAD) statistical outlier detection, and acute air pollution event detection.
* **Machine Learning Pipeline:** Time-series feature engineering (temporal encodings, atmospheric lag features, rolling windows), leak-free chronological splitting (Purged/Expanding Time-Series CV), model training (LightGBM/XGBoost/RandomForest baselines), and batch/real-time inference.
* **Consumption Layer:** High-throughput FastAPI REST services, CLI operational tooling (Typer/Rich), Streamlit monitoring dashboard, and Airflow orchestration DAGs.

---

## 2. Repository Map

```
Air-Quality-Intelligence-main/
├── .github/workflows/           # CI/CD: linting, tests, contract checks, docker build, perf
├── configs/                     # YAML runtime configurations & source definitions
│   ├── base.yaml                # Core pipeline defaults
│   ├── default.yaml             # Environment configuration
│   ├── logging.yaml             # Structured logging setup
│   └── sources/                 # Ingestion endpoints (openaq.yaml, open_meteo.yaml)
├── dags/                        # Apache Airflow Orchestration DAGs
│   ├── aq_hourly_ingest_dag.py  # Hourly fetch -> validate -> transform -> mart update
│   ├── aq_daily_backfill_dag.py # Historical backfill & partition alignment
│   └── aq_model_retrain_dag.py  # Periodic model drift check & re-training
├── dbt/                         # dbt transformation models & tests
│   ├── dbt_project.yml
│   └── models/
│       ├── intermediate/        # Deduplicated & weather-aligned models
│       └── marts/               # Analytical fact tables (hourly_air_quality_facts)
├── docker/                      # Containerization assets
│   ├── Dockerfile.api           # FastAPI application container
│   ├── Dockerfile.base          # Shared base image with common dependencies
│   ├── Dockerfile.dashboard     # Streamlit visualization container
│   ├── Dockerfile.worker        # Ingestion & analytics batch worker
│   ├── health-check.sh          # Container health check utility
│   └── postgres-init/           # PostgreSQL DDL init scripts (01-init-control-plane.sql)
├── docs/                        # Architecture specs, ADRs, Data Contracts, API Schemas
│   ├── 01-system-architecture.md
│   ├── 02-data-contracts.md
│   ├── 03-anomaly-detection-logic.md
│   ├── 05-api-specification.md
│   ├── 06-database-schema.md
│   ├── 07-deployment-guide.md
│   └── 09-architecture-decisions/
├── src/aq_engine/               # Core Python Engine
│   ├── cli.py                   # Typer CLI application entry point
│   ├── config.py                # Pydantic Settings & YAML hierarchical configuration loader
│   ├── common/                  # Shared utilities (exceptions.py, logger.py, time.py)
│   ├── connectors/              # External API adapters (base.py, openaq.py, open_meteo.py)
│   ├── quality/                 # Validation, schema contracts, hashing, deduplication, quarantine
│   ├── storage/                 # Database connection (db.py) and Parquet I/O (parquet_io.py)
│   ├── ingestion/               # Pipeline execution coordinator (orchestrator.py)
│   ├── analytics/               # Aggregation, baseline stats, MAD anomaly, sensor health
│   ├── ml/                      # Time-series splits, feature pipelines, training & inference
│   └── api/                     # FastAPI routes, Pydantic schemas, dependency injection
├── tests/                       # Automated Test Suites
│   ├── unit/                    # Isolated tests for ML, connectors, quality, analytics, CLI
│   ├── integration/             # E2E pipeline, database, DAG structure, and recovery tests
│   └── performance/             # Latency, throughput, and ingestion load benchmarks
├── docker-compose.yml           # Multi-service local/dev orchestration
└── pyproject.toml               # Poetry/Build metadata & tool configurations

```

---

## 3. System Mental Model

```
   [ OpenAQ REST API ]         [ Open-Meteo REST API ]
            │                              │
            └──────────────┬───────────────┘
                           ▼
              ┌────────────────────────┐
              │   Connector Layer      │ (Rate Limit, Retry, Backoff)
              └────────────┬───────────┘
                           ▼
              ┌────────────────────────┐
              │  Data Quality Engine   │ (Contracts, SHA-256 Hash, Range/Null Checks)
              └────┬───────────────┬───┘
     [Passed]      │               │ [Violations]
                   ▼               ▼
     ┌──────────────────┐    ┌─────────────────────────┐
     │ Ingestion Engine │    │ Quarantine Store / DB   │
     └─────┬────────────┘    └─────────────────────────┘
           ├──────────────────────────────┐
           ▼                              ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│ PostgreSQL Relational   │    │ Partitioned Parquet     │
│ Control Plane (Metadata,│    │ Data Lakehouse          │
│ Runs, Health, Alerts)   │    │ (Time-Series Marts)     │
└──────────┬──────────────┘    └──────────┬──────────────┘
           │                              │
           └──────────────┬───────────────┘
                          ▼
              ┌────────────────────────┐
              │ Analytics & ML Engine  │ (MAD Anomalies, Health Scorecards, LightGBM)
              └───────────┬────────────┘
                          ▼
           ┌──────────────┴──────────────┐
           ▼                             ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│ FastAPI Web API Service │    │ Streamlit Dashboard     │
└─────────────────────────┘    └─────────────────────────┘

```

### Problem Statement

Air quality monitoring data from distributed sensors is notoriously noisy: it suffers from transport delays, sensor degradation (calibration drift, flatlines), missing data, schema drift from upstream providers, and temporal misalignment between weather conditions and pollutant readings. The system provides an automated pipeline that ingests heterogeneous environmental data, enforces data quality contracts, detects anomalous readings and sensor failures, and produces forecasts with evaluation against baselines.

### Major Actors & Boundaries

1. **Upstream External Services:** OpenAQ (air monitoring stations) and Open-Meteo (meteorological models).
2. **Orchestrator (Airflow / CLI):** Triggers batch ingestion jobs, transformation runs, and scheduled retraining runs.
3. **Ingestion & Quality Engine (`aq_engine.ingestion`, `aq_engine.quality`):** Validates raw payloads against strict contracts and routes invalid rows to quarantine.
4. **Hybrid Storage Plane (`aq_engine.storage`):** PostgreSQL handles relational entities and transactional metadata; partitioned Parquet files handle append-heavy analytical facts.
5. **Analytics & Machine Learning Layer (`aq_engine.analytics`, `aq_engine.ml`):** Computes rolling statistical indicators, sensor health indices, and forecasts pollutant concentrations.
6. **Consumer Applications (`aq_engine.api`, Streamlit dashboard):** Exposes query interfaces and alerts to downstream clients.

---

## 4. Architecture Overview

### Layered Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Presentation / Consumption                      │
│             FastAPI (REST API)  │  Typer (CLI)  │  Streamlit           │
├────────────────────────────────────────────────────────────────────────┤
│                           Application / ML                             │
│       Analytics Engine  │  Feature Pipeline  │  Model Training/Inference│
├────────────────────────────────────────────────────────────────────────┤
│                          Domain / Pipeline                             │
│     Ingestion Orchestrator  │  Quality Contracts  │  MAD Anomaly Logic  │
├────────────────────────────────────────────────────────────────────────┤
│                          Infrastructure / I/O                          │
│   HTTP Connectors (OpenAQ/OpenMeteo) │ PostgreSQL (psycopg2/SQLA)      │
│   PyArrow Parquet Engine             │ Airflow DAG Scheduling Engine   │
└────────────────────────────────────────────────────────────────────────┘

```

### Architectural Decisions & Explanations

#### 1. Dual-Tier Hybrid Storage Architecture

* **Implementation:** PostgreSQL (`docker/postgres-init/01-init-control-plane.sql`, `src/aq_engine/storage/db.py`) + Partitioned Parquet via PyArrow (`src/aq_engine/storage/parquet_io.py`).
* **Evidence:** Observable from schema DDL and Parquet partitioning helper functions (`year=YYYY/month=MM/location_id=...`).
* **Engineering Inference:** Time-series sensor data consists of high-volume immutable appends where columnar compression (Snappy/ZSTD) saves up to 80% disk space and accelerates analytical aggregations. Relational DBs are retained for relational joins, ACID transactions on run logs, and fast primary-key lookups for station metadata.
* **Tradeoffs:** Introduces dual-write/eventual consistency complexity between Parquet datasets on disk and PostgreSQL metadata tables.

#### 2. Median Absolute Deviation (MAD) for Anomaly Detection

* **Implementation:** `src/aq_engine/analytics/anomaly.py` and `docs/09-architecture-decisions/004-anomaly-detection-mad.md`.
* **Evidence:** Direct implementation in code with parameterized deviation multipliers.
* **Engineering Inference:** Standard standard-deviation ($\sigma$) bounds suffer from sample distortion when extreme air pollution spikes occur. MAD relies on median statistics, maintaining robustness against extreme outliers.
* **Tradeoffs:** Slightly higher computational overhead compared to mean/variance passes; requires sliding window memory buffers.

#### 3. Content-Addressed Hash Deduplication

* **Implementation:** `src/aq_engine/quality/hashing.py` and `src/aq_engine/quality/deduplication.py`.
* **Evidence:** SHA-256 fingerprint generated across normalized natural keys (`location_id + parameter + timestamp_utc`).
* **Engineering Inference:** Ingestion endpoints frequently re-serve overlapping historical windows. Hashing guarantees idempotent write safety across pipeline re-runs and backfills.

---

## 5. Component Architecture

### Component Breakdown

| Module | Core Responsibility | Key Files | Direct Dependencies | Dependents |
| --- | --- | --- | --- | --- |
| **`connectors`** | External API integration, HTTP retries, rate limiting, and raw payload normalization | `base.py`, `openaq.py`, `open_meteo.py`, `models.py` | `httpx` / `requests`, `pydantic` | `ingestion` |
| **`quality`** | Validation rule evaluation, contract enforcement, deduplication, quarantine | `contracts.py`, `validator.py`, `rules.py`, `hashing.py`, `quarantine.py` | `pydantic`, `pandas`, `hashlib` | `ingestion`, `analytics` |
| **`storage`** | Transactional database access and partitioned columnar file I/O | `db.py`, `parquet_io.py` | `sqlalchemy`, `psycopg2`, `pyarrow` | `ingestion`, `ml`, `api` |
| **`ingestion`** | Orchestrating extract, validate, partition, and commit pipelines | `orchestrator.py` | `connectors`, `quality`, `storage` | `cli`, Airflow DAGs |
| **`analytics`** | Aggregations, sensor health assessment, statistical anomalies | `aggregation.py`, `anomaly.py`, `baselines.py`, `station_health.py`, `events.py` | `numpy`, `pandas`, `scipy` | `ml`, `api`, `cli` |
| **`ml`** | Time-series cross-validation, feature engineering, LightGBM training & scoring | `split.py`, `features.py`, `training.py`, `inference.py`, `baselines.py` | `scikit-learn`, `lightgbm`, `pandas` | `api`, `cli`, Airflow DAGs |
| **`api`** | REST endpoints for observations, forecasts, alerts, and system health | `main.py`, `observations.py` | `fastapi`, `pydantic`, `storage` | External Consumers |
| **`cli`** | Operational CLI interface for manual runs, backfills, inspection | `cli.py` | `typer`, `rich`, `ingestion`, `ml` | DevOps / Data Engineers |

---

## 6. Data Architecture

### Relational Schema (PostgreSQL Control Plane)

```
┌────────────────────────┐         ┌────────────────────────┐
│     stations           │1       *│      sensor_health     │
├────────────────────────┼─────────┼────────────────────────┤
│ PK  id                 │         │ PK   id                │
│     external_id        │         │ FK   station_id        │
│     name               │         │      coverage_ratio    │
│     latitude           │         │      drift_detected    │
│     longitude          │         │      flatline_detected │
│     country            │         │      evaluated_at      │
└──────────┬─────────────┘         └────────────────────────┘
           │1
           │*
┌──────────┴─────────────┐         ┌────────────────────────┐
│     anomaly_events     │         │     ingestion_runs     │
├────────────────────────┼─┐       ├────────────────────────┤
│ PK  id                 │ │       │ PK   run_id            │
│ FK  station_id         │ │       │      source_name       │
│     parameter          │ │       │      started_at        │
│     value              │ │       │      completed_at      │
│     z_score / mad_diff │ │       │      rows_ingested     │
│     detected_at        │ │       │      rows_quarantined  │
└────────────────────────┘ │       │      status            │
                           │       └────────────────────────┘
                           │
                           │       ┌────────────────────────┐
                           │       │   quarantine_records   │
                           │       ├────────────────────────┤
                           └──────*│ PK   id                │
                                   │      source            │
                                   │      payload_raw       │
                                   │      failure_reason    │
                                   │      created_at        │
                                   └────────────────────────┘

```

### Partitioned Analytical Lakehouse Layout

```
data/
├── raw/
│   └── source=openaq/
│       └── year=YYYY/
│           └── month=MM/
│               └── data_batch_<run_id>.parquet
├── processed/
│   └── hourly_facts/
│       └── year=YYYY/
│           └── month=MM/
│               └── station_id=ST_XYZ/
│                   └── part_000.parquet
└── quarantine/
    └── year=YYYY/
        └── month=MM/
            └── rejected_records_<timestamp>.parquet

```

---

## 7. Runtime Flows

### 1. Ingestion, Validation, and Storage Pipeline

```
[Airflow DAG / CLI: aq ingest]
  │
  ├─► 1. Entry Point: aq_engine.cli:ingest() / aq_engine.ingestion.orchestrator:IngestionOrchestrator.run()
  │
  ├─► 2. API Fetch: aq_engine.connectors.openaq:OpenAQConnector.fetch_measurements(since, until)
  │      └─► Handles HTTP retries, exponential backoff, rate limit pacing, and raw JSON parsing.
  │
  ├─► 3. Data Quality Gate: aq_engine.quality.validator:DataQualityValidator.validate(raw_df)
  │      ├─► Contract Verification: checks data types, required fields, and non-null constraints.
  │      ├─► Value Range Rules: pollutant concentrations bounded within physical range:
  │      │     (e.g., $0 \le \text{PM}_{2.5} \le 1000\,\mu\text{g/m}^3$).
  │      └─► SHA-256 Hash Deduplication: computes fingerprint across (location_id, parameter, timestamp_utc).
  │
  ├─► 4. Partition Branching:
  │      ├─► [Quarantine Records] ──► aq_engine.quality.quarantine:QuarantineHandler.route()
  │      │                            └─► Writes invalid payloads to PostgreSQL quarantine_records & parquet.
  │      └─► [Clean Records] ───────► aq_engine.storage.parquet_io:ParquetWriter.append_partitioned()
  │                                   └─► Atomically writes partitioned snappy-compressed Parquet files.
  │
  └─► 5. Audit Logging: aq_engine.storage.db:DatabaseManager.log_ingestion_run()
         └─► Records run metadata, ingested row count, and execution latency in PostgreSQL.

```

### 2. Anomaly Detection and Health Scoring Flow

```
[Scheduled Ingestion Completion Event]
  │
  ├─► 1. Trigger: aq_engine.analytics.anomaly:AnomalyDetector.evaluate_window(window_hours=24)
  │
  ├─► 2. Data Retrieval: aq_engine.storage.parquet_io:ParquetReader.read_slice(station_id, window)
  │
  ├─► 3. Computation:
  │      ├─► Calculate rolling median $\tilde{x}$ and $\text{MAD} = \text{median}(|x_i - \tilde{x}|)$.
  │      ├─► Flag reading $x_i$ if $|x_i - \tilde{x}| > k \times \text{MAD}$ (where $k=3.5$).
  │      └─► Run flatline detector: check if $\sigma(x_{t-W \dots t}) < \epsilon$ across consecutive timesteps.
  │
  └─► 4. Persistence & Alerting:
         ├─► Insert detected anomaly events into PostgreSQL `anomaly_events`.
         └─► Update station status in `sensor_health` scorecard table.

```

---

## 8. Machine Learning Pipeline & Time-Series Design

```
Raw Multi-Modal Data (Air Quality Parquet + Weather Parquet)
                         │
                         ▼
          ┌─────────────────────────────┐
          │     Feature Engineering     │  aq_engine.ml.features
          │  - Temporal encodings       │  (sin/cos hour, day of week)
          │  - Lag features             │  (t-1, t-3, t-6, t-24)
          │  - Rolling stats            │  (rolling mean, std, min, max)
          │  - Cross-source alignment   │  (weather variables: temp, humidity, wind)
          └──────────────┬──────────────┘
                         ▼
          ┌─────────────────────────────┐
          │  Purged Time-Series Split   │  aq_engine.ml.split
          │  - Expanding window CV      │  (Zero future data leakage)
          │  - Embargo buffer margin    │
          └──────────────┬──────────────┘
                         ▼
          ┌─────────────────────────────┐
          │    Model Training Bench     │  aq_engine.ml.training
          │  - Naive & Rolling Baseline │  aq_engine.ml.baselines
          │  - LightGBM / XGBoost Regr  │
          └──────────────┬──────────────┘
                         ▼
          ┌─────────────────────────────┐
          │     Evaluation & Metrics    │  aq_engine.ml.evaluation
          │  - RMSE, MAE, WAPE, R²      │
          │  - Baseline uplift validation
          └─────────────────────────────┘

```

---

## 9. Important Software Engineering Patterns

* **Strategy Pattern (Connectors):** `BaseConnector` defines the ingestion interface; `OpenAQConnector` and `OpenMeteoConnector` implement provider-specific endpoint parsing, pagination, and rate limiting.
* **Repository & Data Access Pattern:** `storage.db.DatabaseManager` and `storage.parquet_io.ParquetWriter` isolate raw SQL and file system protocols from business logic.
* **Pydantic Data Contracts:** Domain input boundaries are guarded by runtime Pydantic validation models, converting untyped HTTP payloads into verified immutable records.
* **Idempotent Ingestion Pattern:** Cryptographic content fingerprinting ensures repeated batch ingestion passes produce zero duplicate records in analytical tables.
* **Dead-Letter / Quarantine Pattern:** Malformed rows are segregated into quarantine partitions alongside validation error codes, preventing pipeline crashes while preserving observability.

---

## 10. Architecture Decision Records (ADR Summary)

### ADR-001: PostgreSQL + Partitioned Parquet Hybrid Storage

* **Decision:** Retain PostgreSQL for control-plane relational metadata and store time-series facts in partitioned Parquet files.
* **Evidence:** Explicitly documented in `docs/09-architecture-decisions/001-postgresql-parquet-choice.md`.
* **Tradeoffs:** High scan performance and low storage costs for columnar analytics, but requires managing cross-store synchronization.
* **Reconsideration Trigger:** If concurrent point-writes exceed several thousand queries/second or real-time random row updates are mandated, migrate analytical storage to ClickHouse or Apache Pinot.

### ADR-002: Median Absolute Deviation (MAD) over Z-Score for Outlier Detection

* **Decision:** Implement MAD as the primary statistical anomaly detection algorithm.
* **Evidence:** `src/aq_engine/analytics/anomaly.py` and `docs/09-architecture-decisions/004-anomaly-detection-mad.md`.
* **Tradeoffs:** Resistant to extreme pollutant spikes (masking effect), but requires higher CPU computation than standard variance calculations.
* **Reconsideration Trigger:** If multi-sensor spatial correlations need to be jointly evaluated across networks, migrate to isolation forests or graph neural networks.

---

## 11. Security, Reliability & Performance Analysis

### Security Posture

* **Configuration Decoupling:** Credentials, DB passwords, and API tokens are loaded via environment variables and Pydantic Settings (`src/aq_engine/config.py`).
* **SQL Injection Resistance:** SQLAlchemy / parameterized bindings are strictly enforced across relational repositories.
* **Quarantine Sanitization:** Raw payloads written to audit tables are structured to avoid raw SQL/script execution vulnerabilities.

### Reliability & Fault Tolerance

* **Exponential Backoff & Retries:** Built into API clients to absorb transient network failures and HTTP 429 / 503 status codes.
* **Defensive Pipeline Execution:** Ingestion batch failures are isolated; an invalid record fails only its local row validation (routing to quarantine) without aborting the entire batch.

### Performance Profile

* **Columnar Pruning:** Parquet reads prune files by directory partition (`year`, `month`, `station_id`), avoiding full-table scans.
* **Memory-Efficient Batching:** Ingestion streaming and iterator-based file writes prevent out-of-memory (OOM) errors during large multi-year backfills.

---

## 12. Weaknesses, Technical Debt & Risks

### Actual Problems (Observable in Repository)

1. **No Distributed Lock on Batch File Writes:** `storage/parquet_io.py` writes directly to the local/mounted file system without a file locking mechanism or atomic rename step, creating potential race conditions if multiple worker containers write to the same partition concurrently.
2. **Missing Async Connector Execution:** Connectors use synchronous HTTP client logic inside batch processes, creating I/O wait bottlenecks during high-volume multi-station backfills.

### Potential Scalability Risks

1. **Local File System Lakehouse:** Without an object store abstraction (e.g., S3/GCS using MinIO or `s3fs`), horizontal scaling across multiple containerized worker nodes is constrained by shared volume mounts.

---

## 13. Structured Learning Curriculum

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Curriculum Roadmap                              │
│                                                                        │
│  [Level 1: Fundamentals]  ──► Ingestion, Config, Schemas, Connectors   │
│  [Level 2: Intermediate]  ──► Quality Contracts, Hashing, Parquet I/O  │
│  [Level 3: Advanced]      ──► MAD Anomalies, Sensor Health, ML Leakage │
│  [Level 4: Architecture]  ──► Hybrid Storage, Airflow DAGs, Resilience │
└────────────────────────────────────────────────────────────────────────┘

```

### Level 1: Foundations & Ingestion Mechanics

* **Topics:** Configuration management with Pydantic, HTTP resilience, connector abstraction.
* **Key Files:** `src/aq_engine/config.py`, `src/aq_engine/connectors/base.py`, `src/aq_engine/connectors/openaq.py`.
* **Prerequisites:** Python 3.11+, HTTP protocol, REST APIs, JSON parsing.
* **Questions to Answer:** How does `BaseConnector` enforce retry backoff? Where are API rate limits handled?
* **Hands-on Exercise:** Implement a mock connector that simulates an unreliable HTTP endpoint returning 429 status codes and verify the backoff behavior.

### Level 2: Data Quality, Hashing & Storage

* **Topics:** Data contracts, SHA-256 content deduplication, Parquet columnar partitioning.
* **Key Files:** `src/aq_engine/quality/contracts.py`, `src/aq_engine/quality/hashing.py`, `src/aq_engine/storage/parquet_io.py`.
* **Prerequisites:** Columnar storage vs. row storage, cryptographic hashing, relational schema design.
* **Questions to Answer:** Why is hashing preferable to database auto-incrementing IDs for deduplication? How are Parquet partitions structured on disk?
* **Hands-on Exercise:** Write a test verifying that identical payloads processed twice generate the exact same hash and result in zero duplicate records in the Parquet store.

### Level 3: Analytics, Statistical Anomalies & ML Forecasting

* **Topics:** Median Absolute Deviation (MAD), sensor drift/flatline algorithms, leakage-free time-series cross-validation.
* **Key Files:** `src/aq_engine/analytics/anomaly.py`, `src/aq_engine/analytics/station_health.py`, `src/aq_engine/ml/split.py`, `src/aq_engine/ml/features.py`.
* **Prerequisites:** Non-parametric statistics, time-series feature engineering, LightGBM/XGBoost.
* **Questions to Answer:** Why does standard $Z$-score fail during severe air pollution events? How does `ml.split` prevent future data leakage?
* **Hands-on Exercise:** Inject synthetic flatline and calibration drift anomalies into a clean time-series dataset and verify that `StationHealthEvaluator` detects them.

### Level 4: Systems Architecture & Production Operations

* **Topics:** Hybrid storage consistency, Airflow workflow orchestration, API service design.
* **Key Files:** `dags/aq_hourly_ingest_dag.py`, `src/aq_engine/api/main.py`, `docker-compose.yml`.
* **Prerequisites:** Distributed systems concepts, container networking, DAG task graphs.
* **Architectural Exercise:** Design an architectural migration plan to replace the local file system Parquet store with an AWS S3/MinIO cloud object store without breaking the `FastAPI` query layer.

---

## 14. Knowledge Gaps & Unverifiable Assumptions

1. **Production Cluster Topology:** While `docker-compose.yml` provides a complete local multi-container environment, the repository does not contain Kubernetes manifests (Helm/K8s) or cloud infrastructure code (Terraform). Production replica counts and cluster autoscaling rules cannot be determined directly from the codebase.
2. **Upstream SLA Guarantees:** The repository code accounts for rate limits and retries, but the exact SLA, historical retention limits, and rate caps of the upstream OpenAQ production tier cannot be determined solely from repository files.

---

## 15. Recommended Deep-Dive Order

To systematically master this codebase, explore the components in the following execution sequence:

1. **`src/aq_engine/config.py` & `configs/base.yaml**`: Understand how runtime settings and source parameters are structured and loaded.
2. **`src/aq_engine/connectors/`**: Inspect how external REST APIs are wrapped, paginated, and typed.
3. **`src/aq_engine/quality/`**: Learn how contracts, validation rules, content hashing, and quarantine routing protect data integrity.
4. **`src/aq_engine/storage/`**: Trace how validated data is written to PostgreSQL control tables and partitioned Parquet files.
5. **`src/aq_engine/ingestion/orchestrator.py`**: Trace the end-to-end extraction and ingestion lifecycle.
6. **`src/aq_engine/analytics/`**: Study the MAD outlier detection formulas, rolling window calculations, and sensor health scoring metrics.
7. **`src/aq_engine/ml/`**: Walk through the feature generation pipeline, leak-free time-series cross-validation, baseline comparisons, and model training routines.
8. **`src/aq_engine/api/` & `dags/**`: Examine how endpoints expose analytics/forecasts to clients and how Airflow schedules recurring operations.