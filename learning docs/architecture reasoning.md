This document details 6 architecture-change scenarios across increasing levels of difficulty for the completed **Air Quality Intelligence Engine** repository (`aq_engine`). Each scenario includes requirements, deep technical reasoning, risk analyses, test strategies, and architectural tradeoff comparisons against the existing architecture.

---

### Level 1 — Small Changes: Adding Sensor Accuracy / Confidence Score

#### 1. Requirement

Extend the ingestion pipeline, parquet storage, validation layer, and API to capture an optional sensor accuracy/confidence score `confidence_score` (float between `0.0` and `1.0`) across OpenAQ observations. Expose this field in the `/api/v1/observations` endpoint and quarantine records where `confidence_score` is present but falls outside `[0.0, 1.0]`.

#### 2. Reasoning & Analysis

* **Components to Change:**
* **Connectors & Schema Models:** `src/aq_engine/connectors/models.py` (add `confidence_score: Optional[float] = None` to `ObservationRecord`).
* **Quality & Validation Rules:** `src/aq_engine/quality/rules.py` and `validator.py` (add `CONFIDENCE_SCORE_RANGE` check: $0.0 \le score \le 1.0$), and `contracts.py`.
* **Storage IO & Schemas:** `src/aq_engine/storage/parquet_io.py` (update PyArrow schema definitions to include `pa.float64()` for `confidence_score`).
* **API Presentation:** `src/aq_engine/api/observations.py` and `src/aq_engine/api/main.py` response serializers.
* **DB Control Plane (if tracking aggregate sensor stats):** `docker/postgres-init/01-init-control-plane.sql` (migration script for schema bump).


* **Why:** Ingestion contracts and storage layers enforce strict schemas. Omitting the field at the storage layer causes silent schema drift or PyArrow parquet write failures.
* **Risks:**
* Backward incompatibility with existing parquet partitions lacking the `confidence_score` column when reading historical data.
* Late-arrival deduplication hashing changes if `confidence_score` is inadvertently included in the record hash computation (`src/aq_engine/quality/hashing.py`).


* **Testing Strategy:**
* Unit tests in `tests/unit/test_data_quality.py` for out-of-bound float validation ($<0$ or $>1.0$).
* Schema backward-compatibility tests in `tests/unit/test_parquet_io.py` asserting parquet files written under the old schema read correctly with fill-nulls.
* API response serialization tests in `tests/unit/test_api_observations.py`.


* **Architectural Tradeoffs:** Schema evolution flexibility vs. binary compatibility overhead in columnar storage.

#### 3. Solution vs. Existing Architecture Comparison

* **Existing Architecture:** Reads strict PyArrow schemas and relies on deterministic 5-tuple deduplication hashes (`location_id`, `parameter`, `timestamp`, `latitude`, `longitude`).
* **Change Implementation:** The schema in `parquet_io.py` should be updated with a nullable float field. Ensure `hashing.py` is **not** altered so record identity remains stable regardless of sensor calibration metadata updates.

---

### Level 2 — Feature Changes: Dynamic Multi-Pollutant Alert Routing

#### 1. Requirement

Introduce an alerting capability that evaluates real-time Air Quality Index (AQI) threshold breaches across composite pollutants ($\text{PM}_{2.5}$, $\text{NO}_2$, $\text{O}_3$) alongside weather conditions (e.g., stagnant wind speeds $< 1.5\text{ m/s}$) and dispatches webhooks or Slack notifications to subscribers based on geographic polygons.

#### 2. Reasoning & Analysis

* **Components to Change:**
* **Analytics & Events Module:** `src/aq_engine/analytics/events.py` and `anomaly.py` to add multi-variate event triggers.
* **Database/Control Plane:** `src/aq_engine/storage/db.py` to store webhook subscription rules and geographic boundary registrations.
* **Pipeline/Orchestrator:** `src/aq_engine/ingestion/orchestrator.py` or `dags/aq_hourly_ingest_dag.py` to append an alert-dispatch task immediately after intermediate validation and alignment.
* **Common / Network Client:** New notification dispatcher module with retry policies.


* **Why:** The existing anomaly module evaluates Median Absolute Deviation (MAD) on single time series; alert subscriptions require multi-dimensional rule evaluation and geographic spatial matching.
* **Risks:**
* Blocking ingestion pipelines with synchronous external HTTP webhook calls.
* Alert storms: high-frequency bursts of duplicate notifications during sustained hazardous pollution events.


* **Testing Strategy:**
* Mock external webhook endpoints with HTTP 500/timeout behaviors in `tests/integration/`.
* Unit test debouncing/deduplication windows in `tests/unit/test_event_detection.py`.


* **Architectural Tradeoffs:** Synchronous pipeline execution (simple, guaranteed ordering) vs. asynchronous decoupled event queue (high throughput, requires external broker).

#### 3. Solution vs. Existing Architecture Comparison

* **Existing Architecture:** Processes batches via Airflow DAGs (`aq_hourly_ingest_dag.py`), persists marts to Parquet, and writes execution metadata to PostgreSQL.
* **Change Implementation:** Alerts should be decoupled from the ingestion DAG. The ingestion DAG persists anomaly records to PostgreSQL `anomaly_events` table; a lightweight worker consumes unnotified events, debounces against active subscriptions, and dispatches asynchronously.

---

### Level 3 — Infrastructure Changes: Introducing Redis as a Distributed Caching & Rate-Limiting Layer

#### 1. Requirement

Introduce Redis into the infrastructure stack to cache frequent REST API `/api/v1/observations` and `/api/v1/analytics` queries (TTL: 15 minutes) and implement a sliding-window rate limiter per API key (100 req/min) to protect upstream compute.

#### 2. Reasoning & Analysis

* **Components to Change:**
* **Deployment/Infra:** `docker-compose.yml`, `docker/Dockerfile.api`, and environment configs `configs/base.yaml`, `.env.example`.
* **API Layer:** `src/aq_engine/api/main.py` (FastAPI dependency injection and middleware for rate limiting).
* **Storage / Cache Service:** Create `src/aq_engine/storage/cache.py` wrapping `redis-py` connection pooling.


* **Why:** Disk I/O scans on Parquet partitions for API requests introduce latency and resource contention during concurrent DAG runs.
* **Risks:**
* Cache stampedes when the 15-minute TTL expires on high-traffic stations.
* Stale data served when backfill DAG runs update historical observations.


* **Testing Strategy:**
* API integration tests using `fakeredis` in `tests/unit/test_api_observations.py`.
* Performance test `tests/performance/test_api_performance.py` validating 95th percentile latency reduction and 429 Too Many Requests enforcement.


* **Architectural Tradeoffs:** Increased operational complexity (stateful Redis cluster) vs. lower read latency and API server protection.

#### 3. Solution vs. Existing Architecture Comparison

* **Existing Architecture:** FastApi directly queries parquet files via PyArrow and DB control plane without intermediate caching.
* **Change Implementation:** Implement cache-aside pattern in `src/aq_engine/api/` with cache invalidation triggered via ingestion DAG completion hooks (`on_success_callback` in Airflow).

---

### Level 4 — Scale: Scaling Ingestion to 100x Sensor Volume (10,000+ Stations)

#### 1. Requirement

Scale the system to ingest, validate, and compute anomalies for 10,000 global stations generating 1-minute time series intervals (from current hourly batches of ~100 stations), processing over 14.4 million records daily.

#### 2. Reasoning & Analysis

* **Components to Change:**
* **Ingestion Pipeline:** Migrate from single-threaded batch fetchers in `src/aq_engine/connectors/openaq.py` to asynchronous / concurrent batching with `httpx.AsyncClient` or worker pools.
* **Storage Layout:** Partition pruning in `src/aq_engine/storage/parquet_io.py` must transition from `date=YYYY-MM-DD` to hierarchical `year=YYYY/month=MM/day=DD/station_id=XXX/` or geo-hash partitioning to avoid file-system metadata bottlenecks.
* **Compute Layer:** Move DBT/analytics execution from local single-node pandas/numpy computations to distributed Ray or DuckDB out-of-core memory execution.


* **Why:** Single Pandas DataFrames will exceed memory limits ($>32\text{ GB}$ RAM spikes), and Airflow task concurrency will saturate connector HTTP connection pools.
* **Risks:**
* Small-file problem in Parquet storage if partitions are sliced too granularly.
* PostgreSQL connection pool exhaustion on the control plane.


* **Testing Strategy:**
* Synthetic high-volume benchmarks in `tests/performance/test_ingestion_performance.py`.
* Load testing partition query performance under DuckDB/PyArrow scans.


* **Architectural Tradeoffs:** Vertical scaling simplicity vs. horizontal distributed file partitioning and compute coordination overhead.

#### 3. Solution vs. Existing Architecture Comparison

* **Existing Architecture:** Executes local Pandas transformations and writes unified daily Parquet files.
* **Change Implementation:** Retain DuckDB/Arrow zero-copy reads, implement batch chunking of stations in parallel Airflow task groups, and configure compactor jobs to merge small 1-minute Parquet batches into optimized hourly columnar blocks.

---

### Level 5 — Failure: External Source Outage & Upstream Schema Corruption

#### 1. Requirement

Ensure resilient zero-downtime operation when external APIs (OpenAQ or Open-Meteo) fail completely for $>24$ hours, intermittently return HTTP 503s with exponential backoff triggers, or return malformed JSON payloads missing critical coordinates (`latitude`/`longitude`).

#### 2. Reasoning & Analysis

* **Components to Change:**
* **Connectors:** `src/aq_engine/connectors/base.py` (implement circuit breakers and backoff policies with jitter via `tenacity`).
* **Quarantine Pipeline:** `src/aq_engine/quality/quarantine.py` and `validator.py` (route schema-corrupted payloads directly to quarantine storage without failing DAG execution).
* **Analytics / Baselines:** `src/aq_engine/analytics/baselines.py` and `ml/inference.py` (switch to synthetic autoregressive fallback imputation when real-time readings are missing).


* **Why:** Unhandled external upstream exceptions break Airflow schedule dependencies and leave gaps in analytics datasets.
* **Risks:**
* Cascading DAG failures blocking downstream model retraining jobs.
* Quarantining excessive volumes during transient schema changes without operator awareness.


* **Testing Strategy:**
* Chaos/failure recovery tests in `tests/integration/test_failure_recovery.py` simulating connection drops, 503 Service Unavailable, and malformed payload injection.


* **Architectural Tradeoffs:** Immediate hard-failure alerting vs. graceful degradation with imputed data.

#### 3. Solution vs. Existing Architecture Comparison

* **Existing Architecture:** Uses standard retry mechanisms, writes quarantined rows to separate storage, and logs errors.
* **Change Implementation:** Integrate circuit breakers in `base.py` to prevent thread starvation, and emit health status updates to `01-init-control-plane.sql` table `source_sync_state` to inform the API health check (`/api/v1/health`) of degraded upstream sources.

---

### Level 6 — Architectural Redesign: Transitioning from Batch DAGs to Event-Driven Microservices

#### 1. Requirement

Redesign the core system from a batch-scheduled Airflow architecture into a real-time event-driven streaming architecture using Apache Kafka / Redpanda, transforming ingestion, data quality validation, anomaly detection, and ML scoring into continuous microservices.

```
+----------------------------------------------------------------------------------------------------+
|                                    EVENT-DRIVEN ARCHITECTURE                                       |
+----------------------------------------------------------------------------------------------------+

   [ Ingestion Service ]              [ Validation Service ]            [ Streaming Analytics / ML ]
             │                                   │                                     │
             ▼                                   ▼                                     ▼
     ┌───────────────┐     raw-events    ┌───────────────┐   clean-events      ┌───────────────┐
     │ OpenAQ/Meteo  │ ────────────────> │  Data Quality │ ──────────────────> │ Real-time MAD │
     │  Poller/Push  │                   │ & Quarantine  │                     │ & Inferencing │
     └───────────────┘                   └───────┬───────┘                     └───────┬───────┘
                                                 │                                     │
                                                 │ invalid-events                      │
                                                 ▼                                     ▼
                                         ┌───────────────┐                     ┌───────────────┐
                                         │  Dead Letter  │                     │  Sink Service │
                                         │  Queue (DLQ)  │                     │(Parquet/Icebg)│
                                         └───────────────┘                     └───────────────┘

```

#### 2. Reasoning & Analysis

* **Components to Change:**
* **Core Ingestion:** Deprecate `dags/aq_hourly_ingest_dag.py` in favor of containerized daemon ingestion workers (`docker/Dockerfile.worker`).
* **Messaging Infrastructure:** Introduce Kafka / Redpanda brokers with partitioned topics (`aq.raw-observations`, `aq.validated-observations`, `aq.anomalies`, `aq.dead-letter-queue`).
* **Quality Engine:** Rewrite `validator.py` and `deduplication.py` into a stream processor (e.g., Faust-Streaming or Bytewax) utilizing sliding-window state stores for late-arrival tracking.
* **Storage Sink:** Implement continuous streaming sink workers to write partitioned Parquet/Apache Iceberg tables on S3/MinIO.


* **Why:** Batch execution limits analytics freshness to hourly boundaries; time-sensitive environmental warnings require sub-second to sub-minute latency.
* **Risks:**
* Managing distributed stream state (stateful deduplication over sliding windows).
* Exactly-once vs. at-least-once processing semantics during worker node restarts.
* Dramatic increase in deployment topology complexity.


* **Testing Strategy:**
* End-to-end integration tests using `testcontainers-python` with embedded Redpanda brokers.
* Out-of-order event injection to verify stream watermarking and late-arrival quarantine.


* **Architectural Tradeoffs:** Sub-second latency and continuous processing at the expense of operational complexity, stateful stream recovery overhead, and increased infrastructure cost.

#### 3. Solution vs. Existing Architecture Comparison

* **Existing Architecture:** Scheduled Airflow orchestrator triggering batch CLI entry points (`aq_engine.cli:app`), serializing intermediate tables via DBT and Parquet files.
* **Change Implementation:** The modular structure of `aq_engine` allows individual Python modules (`quality/rules.py`, `analytics/anomaly.py`, `ml/inference.py`) to be decoupled from Airflow and imported directly into streaming event consumers, preserving business logic while modernizing the transport and execution layers.