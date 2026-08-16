# Senior Engineering Examination & System Evaluation Document

**Target Repository:** `Air-Quality-Intelligence-main`

**Focus Areas:** Ingestion, Analytics, ML Pipelines, Quality Contracts, Storage, and Serving.

---

### Level 1 — Repository Structure

**Question:**

Walk through the directory layout of `Air-Quality-Intelligence-main`. Explain the specific architectural responsibility of each top-level directory (`src/aq_engine`, `dags/`, `dbt/`, `configs/`, `docker/`, `docs/`, `tests/`) and identify where the core operational engine resides.

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** The structure separates data engineering orchestration (`dags`), transformation marts (`dbt`), container infrastructure (`docker`), centralized configuration schemas (`configs`), comprehensive testing suites (`tests`), and core python package logic (`src/aq_engine`).
* **Candidate Answer:**
* `src/aq_engine/`: The core business domain package containing modular subpackages: `analytics`, `api`, `common`, `connectors`, `ingestion`, `ml`, `quality`, and `storage`.
* `dags/`: Contains Apache Airflow DAG definitions for scheduled operations (`aq_hourly_ingest_dag.py`, `aq_daily_backfill_dag.py`, `aq_model_retrain_dag.py`).
* `dbt/`: Contains SQL data models (staging/intermediate deduplication, marts for hourly air quality and weather facts) and data contract/test definitions.
* `configs/`: YAML-driven hierarchy providing baseline parameters, source endpoints (OpenAQ, Open-Meteo), logging formats, and ingestion configurations.
* `docker/`: Multi-stage Dockerfiles (`Dockerfile.base`, `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.dashboard`), initialization SQL scripts, and container health probes.
* `tests/`: Multi-tier test suite divided into `unit/`, `integration/`, and `performance/`.


* **Score:** 10/10

---

### Level 2 — Components & Responsibilities

**Question:**

Which component owns the responsibility of ingesting raw payload data from upstream sources, standardizing it, validating it against contracts, and routing corrupted records? Detail the exact submodules involved.

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** The ingestion pipeline does not let raw HTTP responses hit the database or storage without strict boundary enforcement.
* **Candidate Answer:**
* `aq_engine.connectors`: Houses `OpenAQConnector` and `OpenMeteoConnector` extending `BaseConnector`, transforming remote JSON responses into validated Pydantic schemas (`ObservationRecord`, `WeatherRecord`).
* `aq_engine.quality`: Manages data contract enforcement (`contracts.py`), validation rules (`validator.py`, `rules.py`), deduplication hashing (`deduplication.py`, `hashing.py`), and late arrival tracking (`late_arrival.py`).
* `aq_engine.quality.quarantine`: Isolates invalid records failing data contracts (e.g., negative pollutant concentrations, future timestamps, out-of-bound geo-coordinates) by writing quarantine markers rather than aborting batch execution.
* `aq_engine.ingestion.orchestrator`: Ties connector polling, validation checks, quarantine routing, and storage calls together into an idempotent run step.


* **Score:** 10/10

---

### Level 3 — End-to-End Data Flow

**Question:**

Trace the end-to-end data flow of an hourly ingest cycle from external API polling to final consumption via the REST API. Where is the transaction boundary, and where does compute take place?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** Identifies boundaries between extract, raw storage, analytical warehouse modeling, ML inference, and OLTP/Serving.
* **Candidate Answer:**
1. **Extraction:** Airflow triggers `aq_hourly_ingest_dag`, calling `IngestionOrchestrator`. Connectors poll OpenAQ and Open-Meteo REST APIs.
2. **Validation & Storage:** Payload is deserialized, validated via `QualityValidator`, deduplicated using SHA-256 fingerprinting of `(station_id, parameter, timestamp)`, and flushed to partition-pruned raw Parquet tables via `aq_engine.storage.parquet_io` and the relational store (`aq_engine.storage.db`).
3. **Transformation:** `dbt` executes transformations compiling `int_air_quality_deduplicated` and `int_weather_aligned` into `hourly_air_quality_facts` and `hourly_weather_facts`.
4. **Analytics & Inference:** `aq_engine.analytics` runs anomaly detection (MAD/rolling baselines) and station health diagnostics, while `aq_engine.ml.inference` computes short-term forecasts using pre-trained regression models.
5. **Serving:** FastAPI application (`aq_engine.api.main`, `observations.py`) queries the facts tables and metadata layer to serve downstream consumers.


* **Transaction Boundary:** Transactions are isolated at the database batch-insert and file-atomic Parquet writer boundaries. Relational control plane metadata updates commit only upon successful ingestion and quarantine logging.


* **Score:** 10/10

---

### Level 4 — Runtime Behavior & Idempotency

**Question:**

What happens if the exact same hourly ingestion request arrives twice, or if a DAG task retries after writing half of its dataset? Where is this assumption enforced?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** Idempotency is enforced at multiple layers rather than relying solely on database primary keys.
* **Candidate Answer:**
* **Hash-Based Deduplication:** `aq_engine.quality.deduplication` generates deterministic hashes across `(station_id, timestamp_utc, parameter_name)`.
* **Database Upserts:** Relational tables define unique compound indexes on the record identity, executing `ON CONFLICT DO NOTHING` or `ON CONFLICT UPDATE` depending on the entity update semantics.
* **Parquet Partition Overwrites:** Parquet storage partition paths are deterministic (e.g., `/year=YYYY/month=MM/day=DD/hour=HH/`). Rerunning an ingestion cycle replaces or safely reconciles the partition target file atomically, preventing partial write pollution.


* **Score:** 10/10

---

### Level 5 — Design Patterns & Code Abstractions

**Question:**

What would happen if we removed the `BaseConnector` abstraction in `aq_engine.connectors.base` and allowed each external client to directly query external APIs inside Airflow tasks?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** Evaluates coupling, error handling resilience, rate limiting, and contract compliance.
* **Candidate Answer:**
* **Tight Coupling & Code Duplication:** Ingestion tasks would directly manage HTTP sessions, pagination mechanics, exponential backoff retries, and error serialization per vendor.
* **Loss of Contract Standardization:** `BaseConnector` enforces consistent mapping from heterogeneous vendor formats into unified Pydantic contracts before analytics see the data.
* **Degraded Testability:** Mocking network boundaries in unit tests (`tests/unit/test_open_meteo_connector.py`) would require patching raw socket/HTTP sessions in every DAG instead of swapping or mocking connector instances.


* **Score:** 10/10

---

### Level 6 — Architectural Decisions & Storage Engine

**Question:**

Why did the system adopt a hybrid storage design (PostgreSQL control plane/metadata + Parquet analytics storage) rather than using a pure relational or pure data-lake approach?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** Evaluates ADR 001 tradeoffs between OLTP transactional integrity and OLAP columnar query efficiency.
* **Candidate Answer:**
* **PostgreSQL (Control Plane & Serving):** Provides ACID compliance for station metadata, user configuration, authentication, pipeline execution tracking, and low-latency point-lookups for real-time API endpoints.
* **Parquet (Analytical Time-Series):** High-compression columnar storage optimized for analytical scanning across millions of pollutant time-series records, vectorization with pandas/pyarrow, and zero-cost S3/object storage scaling without bloating PostgreSQL VACUUM and buffer pool memory.


* **Score:** 10/10

---

### Level 7 — Statistical & ML Tradeoffs

**Question:**

Why did the architecture select Median Absolute Deviation (MAD) over standard Z-score ($\mu \pm 3\sigma$) for baseline anomaly detection in `aq_engine.analytics.anomaly`?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Analysis & Assumptions:** Evaluates statistical robustness in environmental datasets characterized by wild pollution spikes and wildfire events.
* **Candidate Answer:**
* **Vulnerability of Mean and Variance:** The sample mean ($\mu$) and standard deviation ($\sigma$) are non-robust estimators with a breakdown point of 0%. A massive wildfire episode or transient sensor error skews $\mu$ upwards and inflates $\sigma$, causing subsequent severe pollution spikes to be masked as "normal".
* **Robustness of MAD:** Median and MAD have a 50% breakdown point. Extreme outliers do not shift the center or dispersion estimators, allowing accurate isolation of legitimate sensor drift, stuck values, and anomalous environmental episodes.


* **Score:** 10/10

---

### Level 8 — Failure Modes & Boundary Resilience

**Question:**

What happens if the Open-Meteo or OpenAQ external service times out or returns HTTP 429/500 repeatedly during a scheduled DAG run? How does the pipeline recover, and how is downstream data integrity preserved?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Candidate Answer:**
* **Exponential Backoff:** `BaseConnector` executes retry logic with jitter and timeouts.
* **Task Failure & Isolation:** If retries are exhausted, the ingest operator fails cleanly, triggering Airflow alert hooks without corrupting partial staging partitions.
* **Daily Backfill Recovery:** The backfill DAG (`aq_daily_backfill_dag.py`) can re-execute past hourly windows across missing timestamp intervals idempotently.
* **Downstream Null Tolerances:** Feature engineering and dbt intermediate models apply outer-join coalescence, allowing core air quality marts to function even if aligned meteorological data is temporarily unavailable.


* **Score:** 10/10

---

### Level 9 — Security & Contract Hardening

**Question:**

Where are security boundaries enforced regarding API inputs, configuration secrets, database access, and data contract tampering?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Candidate Answer:**
* **Environment Isolation:** Secrets and API keys are injected via environment variables (`.env.example`) and validated via `aq_engine.config.Settings` (Pydantic BaseSettings), preventing hardcoded credentials.
* **API Parameter Validation:** FastAPI router endpoints (`api/observations.py`) validate query parameters (ISO datetimes, bbox coordinates, parameter whitelists) at the serialization boundary using Pydantic, blocking injection vectors.
* **SQL Injection Immunity:** Relational operations use SQLAlchemy/parameterized queries; dbt compiles parameterized Jinja templates rather than dynamic raw string concatenations.
* **Data Contract CI Verification:** GitHub Actions workflow `.github/workflows/data-contract-check.yml` validates schema compatibility against breaking upstream changes before deployment.


* **Score:** 10/10

---

### Level 10 — Performance & Query Optimization

**Question:**

Why is querying historical pollutant percentiles across 50,000 stations inefficient in raw row-based storage, and how does this repository optimize such analytical reads?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Candidate Answer:**
* **Row-Store Inefficiency:** In traditional row-oriented tables, computing aggregates across specific columns requires reading entire rows off disk into memory, resulting in excessive I/O overhead.
* **Parquet Column Pruning & Dictionary Encoding:** In `aq_engine.storage.parquet_io`, columns (e.g., `value`, `parameter`) are stored contiguously. Scans only read the requested column chunks off disk.
* **dbt Fact Mart Pre-Aggregation:** `hourly_air_quality_facts` pre-computes hourly summaries and rolling metrics during pipeline transformation, preventing raw recalculation on every ad-hoc API read.


* **Score:** 10/10

---

### Level 11 — Scalability & Traffic Multipliers

**Question:**

What breaks first if ingest volume and API query traffic both increase by 100x? Which components must be decoupled or scaled horizontally?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Candidate Answer:**
* **Airflow Local Executor & DB Connection Pool:** Ingestion tasks bottleneck on database pool capacity and Airflow task concurrency.
* **File Storage Lock Contention:** High-concurrency single-node filesystem writes to raw Parquet directories will degrade I/O and risk race conditions.
* **FastAPI Direct DB Contention:** Analytical read queries directly hitting Postgres will exhaust CPU and memory pools.
* **Remediation Plan:**
1. Transition ingestion workers to distributed task queues (Celery/KubernetesExecutor).
2. Move Parquet storage from local filesystem paths to an object store (S3/GCS) with partitioned Athena/DuckDB query federation.
3. Introduce a Redis caching layer in front of FastAPI observation endpoints for frequently accessed station statistics.




* **Score:** 10/10

---

### Level 12 — Architectural Redesign

**Question:**

How would you redesign the entire system architecture to support real-time sub-minute streaming anomaly alerts alongside the existing hourly batch reporting, while minimizing redundant compute?

**Evaluation & Candidate Answer:**

* **Evaluation Verdict:** Correct.
* **Candidate Answer:**
* **Unified Kappa/Lambda Hybrid Architecture:**
1. **Streaming Ingestion Tier:** Deploy an event broker (Apache Kafka / AWS Kinesis) where edge connectors push sub-minute observation payloads.
2. **Real-Time Stream Processing:** Use Apache Flink or Faust/Blink consumer workers reading from Kafka to maintain stateful sliding windows (e.g., 10-minute MAD baselines) and emit low-latency anomaly alerts directly to a WebSocket/Webhook notification service.
3. **Micro-Batch Sinks:** The streaming engine micro-batches raw events into an object store in Parquet format every 15–60 minutes.
4. **Analytical Transformation:** dbt and Airflow continue running scheduled batch marts over historical data partitions, eliminating duplicate extract logic while serving both real-time alerts and long-term analytical intelligence.
