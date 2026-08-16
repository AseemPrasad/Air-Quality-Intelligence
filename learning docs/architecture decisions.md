# Architectural & Implementation Decision Analysis: `aq_engine`

---

## 1. Dual-Tier Hybrid Storage (PostgreSQL Control Plane + Partitioned Parquet Lakehouse)

### WHY THIS?

* **What the repository does:** Stores relational station dimensions, ingestion execution runs, data quality audits, sensor health scores, and anomaly events in PostgreSQL, while time-series hourly measurements are stored as partitioned Snappy-compressed Apache Parquet files on disk.


* **Where it is implemented:**
* Relational schema: `docker/postgres-init/01-init-control-plane.sql`, `src/aq_engine/storage/db.py`

* Columnar lakehouse: `src/aq_engine/storage/parquet_io.py`, `dbt/models/marts/`

* Architectural documentation: `docs/09-architecture-decisions/001-postgresql-parquet-choice.md`



* **Problem it solves:** Prevents table bloat, slow range scans, and high I/O overhead associated with storing millions of append-only time-series sensor observations in traditional OLTP relational tables, while preserving ACID transactions for platform execution tracking.


* **Engineering principle:** Polyglot Persistence; separation of transactional state (OLTP) from high-throughput analytical scans (OLAP).
* **Evidence:**
* Direct ADR documentation (`docs/09-architecture-decisions/001-postgresql-parquet-choice.md`).


* DDL in `01-init-control-plane.sql` defines tables for `stations`, `ingestion_runs`, `sensor_health`, and `anomaly_events`, but contains no table definition for raw hourly measurements.


* `src/aq_engine/storage/parquet_io.py` explicitly partitions fact datasets by `year=YYYY/month=MM/` using PyArrow.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: Single Monolithic Relational Database (Pure PostgreSQL)       │
│                                                                             │
│ - Implementation: Ingest raw facts directly into a PostgreSQL table.       │
│ - Advantages: Single connection string, full transactional consistency,     │
│   foreign keys on all measurements, uniform SQL interface.                 │
│ - Disadvantages: High disk consumption (uncompressed row-store), vacuuming  │
│   overhead, performance degradation as indexes exceed available RAM.       │
│ - Complexity: Low.                                                          │
│ - Performance: Slower for wide-range aggregate analytics.                   │
│ - Scalability: Limited by single-node storage and I/O limits.               │
│ - Maintainability: Easy initially, difficult when tables hit >50M rows.     │
│ - Testability: Requires active DB instance for all telemetry tests.         │
│ - Operational Consequences: High IOPS demand and DB backup bloat.           │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: Dedicated Distributed Columnar Store (ClickHouse / Pinot)     │
│                                                                             │
│ - Implementation: Direct ingestion into a ClickHouse cluster.               │
│ - Advantages: Sub-second analytical vector queries, automated replication,  │
│   built-in deduplication (ReplacingMergeTree).                              │
│ - Disadvantages: Additional infrastructure dependency, higher operational   │
│   overhead, complex local testing setup.                                    │
│ - Complexity: High.                                                         │
│ - Performance: Significantly faster than file-based Parquet reads.          │
│ - Scalability: Horizontally scalable across clusters.                       │
│ - Maintainability: High learning curve and cluster maintenance burden.      │
│ - Testability: Requires spinning up ClickHouse test containers.             │
│ - Operational Consequences: Requires dedicated DevOps cluster management.   │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** High columnar compression (saving up to 80% disk space), rapid column projection/partition pruning without indexing overhead, zero software license cost, and minimal runtime infrastructure (operates directly on local/mounted volumes).


* **Sacrificed:** Synchronous cross-store ACID transactions (a write to Parquet and a write to PostgreSQL must be coordinated by application code).



### FAILURE POINT

Becomes problematic when concurrent writes occur across multiple worker processes without a distributed lock or atomic directory rename mechanism in `parquet_io.py`, leading to file overwrite race conditions.

### CHANGE CONDITION

A requirement for interactive, sub-50ms analytical aggregate queries across billions of rows exposed to external web users, or the need for frequent point-updates/deletions on historical sensor readings.

### SCALE CONDITION

Breaks when the number of partition files creates excessive file system inode overhead (e.g., hundreds of thousands of files across thousands of sensor stations) and single-node mounted volumes become I/O bottlenecks.

### LEARNING QUESTION

> *If an ingestion batch successfully writes Parquet partitions to disk but the PostgreSQL process crashes before updating `ingestion_runs`, in what exact state is the system left, and how does the reader reconcile this discrepancy?*

---

## 2. Natural-Key Cryptographic Content Hashing (SHA-256) for Deduplication

### WHY THIS?

* **What the repository does:** Generates a deterministic SHA-256 hexadecimal string from the composite tuple `(location_id, parameter, timestamp_utc)` and uses it to identify and filter out duplicate observations before persistence.


* **Where it is implemented:** `src/aq_engine/quality/hashing.py`, `src/aq_engine/quality/deduplication.py`

* **Problem it solves:** Upstream APIs frequently re-deliver overlapping temporal windows during hourly batch fetches and backfills. Because analytical facts are stored as immutable Parquet files rather than tables with unique constraints, database-level deduplication (`ON CONFLICT DO NOTHING`) cannot be applied at the storage layer.


* **Engineering principle:** Idempotent Ingestion; Content-Addressed Data Integrity.
* **Evidence:**
* `src/aq_engine/quality/hashing.py` provides `generate_record_hash()` formatting natural keys into a normalized string before hashing.


* `tests/integration/test_deduplication.py` and `tests/integration/test_idempotent_ingest.py` assert that re-ingesting identical batches produces zero additional records.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: Database Primary Key / Unique Constraint Enforcement         │
│                                                                             │
│ - Implementation: Rely on PostgreSQL unique index on (station, param, time).│
│ - Advantages: Offloads deduplication entirely to the relational engine.     │
│ - Disadvantages: Couples deduplication logic to PostgreSQL, making file-    │
│   based Parquet storage impossible without staging tables.                  │
│ - Complexity: Low.                                                          │
│ - Performance: Fast for small tables; slows down as index trees expand.     │
│ - Scalability: Bound to database transaction throughput.                    │
│ - Maintainability: Simple schema definitions.                               │
│ - Testability: Requires database engine to test deduplication behavior.     │
│ - Operational Consequences: Database locks on high-concurrency inserts.     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: In-Memory Set / Sliding Bloom Filter Cache                   │
│                                                                             │
│ - Implementation: Maintain a Redis/in-memory Bloom filter of seen keys.     │
│ - Advantages: Extremely fast lookup without disk scans.                     │
│ - Disadvantages: Volatile state; requires warm-up on process restarts;      │
│   Bloom filters introduce probabilistic false positives (dropped data).     │
│ - Complexity: Medium-High.                                                  │
│ - Performance: Sub-millisecond checks.                                      │
│ - Scalability: Limited by cache memory size.                                │
│ - Maintainability: Requires cache invalidation and synchronization logic.   │
│ - Testability: Requires mocking cache services in unit test suites.         │
│ - Operational Consequences: Additional infrastructure point of failure.     │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** Stateless, storage-agnostic deduplication that functions identically in memory, during unit testing, and across local or cloud file systems without requiring an active database connection.


* **Sacrificed:** CPU compute cycles spent computing SHA-256 hashes for every ingested row.



### FAILURE POINT

Fails to deduplicate if timestamps arrive with differing precision formats (e.g., `2026-08-01T10:00:00Z` vs `2026-08-01T10:00:00.000Z`) due to inconsistent string normalization prior to hashing.

### CHANGE CONDITION

A requirement to process high-frequency streaming events (>100,000 events/sec) where SHA-256 CPU hashing overhead creates ingestion pipeline latency bottlenecks.

### SCALE CONDITION

Remains functional across scale, but batch-level deduplication within memory arrays becomes insufficient if duplicate events arrive split across disparate batch execution windows without an existing partition index scan.

### LEARNING QUESTION

> *Why does `generate_record_hash` explicitly exclude the measurement `value` field from the hash generation tuple? What would happen during sensor re-calibrations if `value` were included?*

---

## 3. Median Absolute Deviation (MAD) for Statistical Anomaly Detection

### WHY THIS?

* **What the repository does:** Calculates anomaly scores using Median Absolute Deviation:

$$\text{MAD} = \text{median}(\vert{}x_i - \tilde{x}\vert{})$$



where $\tilde{x} = \text{median}(X)$, and flags observations where the modified $Z$-score exceeds a fixed threshold (default: $3.5$).


* **Where it is implemented:** `src/aq_engine/analytics/anomaly.py`, documented in `docs/09-architecture-decisions/004-anomaly-detection-mad.md`.


* **Problem it solves:** Severe pollution episodes (e.g., crop burning, dust storms, industrial leaks) cause acute pollutant spikes. Standard parametric anomaly detectors using mean ($\mu$) and standard deviation ($\sigma$) suffer from the "masking effect": extreme outlier values artificially inflate $\sigma$, which reduces the computed $Z$-score and causes true anomalies to be missed.


* **Engineering principle:** Robust Non-Parametric Statistics; Fault-Resilient Metric Estimation.
* **Evidence:**
* `docs/09-architecture-decisions/004-anomaly-detection-mad.md` details the mathematical rationale and comparison against $Z$-score and Isolation Forests.


* `src/aq_engine/analytics/anomaly.py` implements the scale factor $1.4826$ for normal distribution consistency.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: Standard Parametric Z-Score (Mean / Standard Deviation)       │
│                                                                             │
│ - Implementation: Flag anomalies where |x - μ| / σ > 3.0.                   │
│ - Advantages: Trivial to implement, highly vectorized, low computational     │
│   complexity (single-pass calculation).                                     │
│ - Disadvantages: Sensitive to extreme values; fails under skewed, non-      │
│   Gaussian air quality distributions (masking effect).                      │
│ - Complexity: Minimal.                                                      │
│ - Performance: O(N) single-pass compute.                                    │
│ - Scalability: High.                                                        │
│ - Maintainability: Simple.                                                  │
│ - Testability: Straightforward unit testing.                                │
│ - Operational Consequences: High false-negative rate during severe events.  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: Machine Learning Isolation Forest / Autoencoders             │
│                                                                             │
│ - Implementation: Train unsupervised tree ensembles or neural autoencoders. │
│ - Advantages: Captures complex multi-variable non-linear interactions       │
│   (e.g., high PM2.5 combined with specific wind speed/humidity).            │
│ - Disadvantages: "Black box" decisions, high training compute, non-         │
│   deterministic outputs, model drift requiring continual re-tuning.         │
│ - Complexity: High.                                                         │
│ - Performance: Expensive inference passes per batch.                        │
│ - Scalability: High memory and compute footprint.                           │
│ - Maintainability: Difficult to debug false alarms in production.           │
│ - Testability: Requires statistical regression testing suites.              │
│ - Operational Consequences: Requires GPU/high CPU inference infrastructure. │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** High breakdown point ($50\%$), mathematical explainability, and outlier resistance without requiring machine learning model training or hyperparameter drift tracking.


* **Sacrificed:** Evaluating rolling medians requires window sorting ($\mathcal{O}(N \log N)$), which is computationally more expensive than single-pass mean/variance calculations ($\mathcal{O}(N)$).

### FAILURE POINT

If more than $50\%$ of the values within a sliding window are identical (e.g., consecutive zero readings), $\text{MAD}$ evaluates to $0.0$, leading to division-by-zero errors unless protected by an explicit epsilon ($\epsilon$) floor.

### CHANGE CONDITION

A requirement to detect multi-dimensional spatial anomalies across adjacent stations (e.g., verifying if a reading is anomalous relative to neighboring geographic sensors rather than its own historical series).

### SCALE CONDITION

Becomes a compute bottleneck if calculated over long rolling windows ($>10,000$ points) across millions of individual IoT devices in real-time streaming pipelines without approximate quantile algorithms (such as $t$-digest).

### LEARNING QUESTION

> *Why does the implementation multiply the denominator MAD by the constant $1.4826$, and under what specific data distribution assumption is this constant derived?*

---

## 4. Purged Time-Series Cross-Validation with Embargo Buffer

### WHY THIS?

* **What the repository does:** Generates non-shuffled, expanding chronological train/validation splits with an explicit temporal purge margin and embargo window between training and validation folds.


* **Where it is implemented:** `src/aq_engine/ml/split.py`

* **Problem it solves:** Standard cross-validation (e.g., $K$-Fold) randomly shuffles observations across time, causing future information to leak into past training sets. Furthermore, autoregressive lag features (e.g., $t-1, t-24$) create serial correlation across the split boundary: samples in the training set contain lag values derived from time points located within the validation window.


* **Engineering principle:** Temporal Integrity; Prevention of Train-Test Data Leakage.
* **Evidence:**
* `src/aq_engine/ml/split.py` implements `TimeSeriesSplitter` with explicit parameters for `n_splits`, `max_train_size`, and `embargo_hours`.


* `tests/unit/test_time_series_split.py` asserts that $\max(\text{train\_indices}) + \text{embargo} < \min(\text{val\_indices})$.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: Standard Scikit-Learn K-Fold Cross-Validation                │
│                                                                             │
│ - Implementation: Randomly partition dataset into K folds.                  │
│ - Advantages: Standard library implementation; maximizes sample usage.      │
│ - Disadvantages: Causes massive data leakage in time-series data, producing │
│   overly optimistic evaluation metrics that collapse in production.         │
│ - Complexity: Low.                                                          │
│ - Performance: Fast.                                                        │
│ - Scalability: High.                                                        │
│ - Maintainability: Trivial.                                                 │
│ - Testability: Standard.                                                    │
│ - Operational Consequences: Deploys broken models to production.            │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: Standard TimeSeriesSplit (Expanding Window without Embargo)  │
│                                                                             │
│ - Implementation: Chronological split where train always precedes test.     │
│ - Advantages: Prevents direct future-to-past leakage.                       │
│ - Disadvantages: Autoregressive features spanning the split boundary leak   │
│   information across adjacent timestamps (serial correlation leakage).      │
│ - Complexity: Low-Medium.                                                   │
│ - Performance: Fast.                                                        │
│ - Scalability: High.                                                        │
│ - Maintainability: Simple.                                                  │
│ - Testability: Straightforward.                                             │
│ - Operational Consequences: Slight performance over-estimation.             │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** Mathematically leak-free validation metrics that accurately reflect real-world out-of-sample forecasting performance.


* **Sacrificed:** Discards a small percentage of valid boundary observations (the embargo buffer size) from model training.



### FAILURE POINT

If the maximum autoregressive lag feature length (e.g., $t-72$) exceeds the configured `embargo_hours` window, feature leakage still occurs across the boundary.

### CHANGE CONDITION

Transitioning from offline batch forecasting to online continual learning, where models update incrementally on streaming data without discrete cross-validation splits.

### SCALE CONDITION

Scales linearly with the number of folds; becomes computationally expensive during hyperparameter tuning if large numbers of expanding folds are evaluated over multi-year datasets.

### LEARNING QUESTION

> *If your feature pipeline generates a rolling 7-day moving average feature ($t-168$), what minimum `embargo_hours` must be passed to `TimeSeriesSplitter` to guarantee zero boundary leakage?*

---

## 5. Shared Single-Source Feature Pipeline Architecture

### WHY THIS?

* **What the repository does:** Centralizes all feature transformations (lag calculation, rolling aggregations, cyclical sine/cosine time encodings, and weather alignments) inside a single class (`FeaturePipeline`) used identically during offline training and real-time/batch inference.


* **Where it is implemented:** `src/aq_engine/ml/features.py`

* **Problem it solves:** "Train-Serve Skew", a common machine learning failure mode where feature generation logic is rewritten separately for the production serving layer, leading to subtle mathematical discrepancies between training features and inference features.


* **Engineering principle:** Single Source of Truth (SSOT); DRY (Don't Repeat Yourself).
* **Evidence:**
* `src/aq_engine/ml/training.py` imports and executes `FeaturePipeline.transform()` during model fitting.


* `src/aq_engine/ml/inference.py` and `src/aq_engine/api/observations.py` invoke `FeaturePipeline.transform()` on raw recent observation slices to generate inference matrices.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: Pre-Computing and Materializing Features via dbt / SQL       │
│                                                                             │
│ - Implementation: dbt models calculate lags and write a wide feature table. │
│ - Advantages: Fast training reads; uses SQL engine optimizations.           │
│ - Disadvantages: High storage overhead (materializing wide lag tables);     │
│   real-time API inference must wait for scheduled dbt execution runs or     │
│   duplicate the feature SQL logic in Python.                                │
│ - Complexity: Medium.                                                       │
│ - Performance: Fast batch reads; high disk consumption.                     │
│ - Scalability: Bound to data warehouse compute capacity.                    │
│ - Maintainability: Splits logic between SQL models and Python inference.    │
│ - Testability: Requires database test runners for feature assertions.       │
│ - Operational Consequences: High storage bloat for historical wide tables.  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: Standalone Feature Store (Feast / Hopsworks)                 │
│                                                                             │
│ - Implementation: Register feature views in a dedicated feature store.      │
│ - Advantages: Point-in-time correct joins, feature registry, managed online │
│   (Redis) and offline (Parquet) synchronization.                            │
│ - Disadvantages: Adds complex operational infrastructure, separate servers, │
│   and steep learning curve for a single-domain engine.                      │
│ - Complexity: Very High.                                                    │
│ - Performance: Sub-10ms online feature retrieval.                           │
│ - Scalability: Enterprise scale.                                            │
│ - Maintainability: High maintenance overhead.                               │
│ - Testability: Requires integration testing with feature store daemon.      │
│ - Operational Consequences: Significant cloud hosting costs and complexity. │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** Guarantees zero train-serve feature skew with zero additional infrastructure dependencies (pure in-memory Python transformations).


* **Sacrificed:** Real-time API forecast endpoints must fetch raw historical time-series slices and compute features on the fly during the HTTP request lifecycle.



### FAILURE POINT

If the historical query window fetched for inference is shorter than the longest lag feature requirement (e.g., fetching 24 hours of history when a 72-hour lag feature is required), the pipeline generates `NaN` feature rows and inference fails.

### CHANGE CONDITION

A requirement for sub-10ms forecast response times across thousands of concurrent API requests, requiring pre-computed feature caching in an in-memory store like Redis.

### SCALE CONDITION

Breaks when the feature calculation dataframe exceeds the memory boundary of a single worker/API container process.

### LEARNING QUESTION

> *Why does `FeaturePipeline` encode the hour of the day as two separate features ($\sin(2\pi h / 24)$ and $\cos(2\pi h / 24)$) instead of a single integer value from 0 to 23?*

---

## 6. Dead-Letter Quarantine Routing for Data Quality Failures

### WHY THIS?

* **What the repository does:** Catches invalid payloads (missing required columns, out-of-bounds physical values, type coercion errors) during validation, isolates the rejected rows, annotates them with specific error codes, and routes them to a dedicated quarantine store (PostgreSQL `quarantine_records` and `/data/quarantine/` Parquet files) without halting or failing the overall pipeline run.


* **Where it is implemented:**
* `src/aq_engine/quality/validator.py`

* `src/aq_engine/quality/quarantine.py`

* `docker/postgres-init/01-init-control-plane.sql` (`quarantine_records` table)




* **Problem it solves:** Ingesting real-world sensor streams from external providers involves frequent transient corruptions (e.g., upstream API schema shifts, sensor transmission errors). If validation throws unhandled exceptions, the entire ingestion batch crashes, blocking clean data from reaching analytical fact tables.


* **Engineering principle:** Dead-Letter Queue (DLQ) Pattern; Fault-Tolerant Ingestion.
* **Evidence:**
* `src/aq_engine/quality/validator.py` returns a structured `ValidationResult` containing both `valid_df` and `quarantine_df`.


* `docker/postgres-init/01-init-control-plane.sql` defines `quarantine_records` with a `jsonb` column `raw_payload` to preserve malformed inputs for root-cause inspection.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: "Fail-Fast" Abort on Validation Error                        │
│                                                                             │
│ - Implementation: Raise an unhandled exception on the first invalid record. │
│ - Advantages: Guarantees zero corrupted records ever enter the system;      │
│   alerts on-call engineers immediately.                                     │
│ - Disadvantages: A single malformed reading from one station aborts the     │
│   ingestion of valid readings from hundreds of other healthy stations.      │
│ - Complexity: Minimal.                                                      │
│ - Performance: N/A (system fails).                                          │
│ - Scalability: Terrible reliability in noisy distributed environments.      │
│ - Maintainability: Results in frequent alert fatigue and manual reruns.    │
│ - Testability: Trivial.                                                     │
│ - Operational Consequences: High pipeline downtime and data ingestion lag.  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: Silent Drop / Coercion (df.dropna / fillna)                  │
│                                                                             │
│ - Implementation: Silently drop invalid rows or fill missing values.        │
│ - Advantages: Pipeline runs without interruptions.                          │
│ - Disadvantages: Causes silent data loss; operators have zero observability │
│   into missing data or upstream provider corruption.                        │
│ - Complexity: Low.                                                          │
│ - Performance: Fast.                                                        │
│ - Scalability: High.                                                        │
│ - Maintainability: Poor auditability.                                       │
│ - Testability: Hard to verify dropped record volume.                        │
│ - Operational Consequences: Unnoticed data gaps corrupt downstream models.  │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** Total pipeline resilience (clean records are persisted, corrupt records are isolated) with full auditability and root-cause debugging capabilities.


* **Sacrificed:** Additional database storage overhead for persisting malformed JSON payloads and maintaining dual output routing logic.



### FAILURE POINT

If an upstream provider introduces a breaking change affecting 100% of rows, the pipeline will complete with status `SUCCESS` while routing all data to quarantine, potentially delaying human intervention unless explicit threshold alerts (e.g., `quarantine_rate > 10%`) are monitored.

### CHANGE CONDITION

A regulatory requirement mandating zero-tolerance ingestion halts whenever an unverified payload is encountered.

### SCALE CONDITION

If millions of corrupt rows arrive continuously during an outage, the `quarantine_records` PostgreSQL table can suffer rapid disk exhaustion due to uncompressed `jsonb` payload storage.

### LEARNING QUESTION

> *In `src/aq_engine/quality/quarantine.py`, why is the raw payload stored as a JSONB object in PostgreSQL rather than mapped to strict tabular columns?*

---

## 7. Baseline Uplift Validation Gate for Machine Learning Retraining

### WHY THIS?

* **What the repository does:** Evaluates newly trained gradient-boosted models (LightGBM) against two non-ML statistical baselines (Persistence: $y_{t+h} = y_t$, and Rolling 24h Mean) across out-of-fold validation splits. The model artifact is serialized and promoted to production *only* if its RMSE and MAE improve upon both baseline models.


* **Where it is implemented:**
* `src/aq_engine/ml/baselines.py`

* `src/aq_engine/ml/training.py` (`ModelTrainer.train()`)




* **Problem it solves:** Complex machine learning models can easily overfit noisy sensor data or degrade during seasonal concept drift, performing worse than simple persistence while consuming significantly more compute. Automated retraining pipelines without validation gates can silently deploy degraded models to production.


* **Engineering principle:** Model Governance; Defensive Deployment; Minimum Viable Performance (MVP) Verification.
* **Evidence:**
* `src/aq_engine/ml/baselines.py` defines `BaselineEvaluator` computing persistence and rolling metrics.


* `src/aq_engine/ml/training.py` raises `ModelUpliftValidationError` if $\text{RMSE}_{\text{lgbm}} \ge \text{RMSE}_{\text{baseline}}$, aborting model artifact overwrite.





### WHY NOT THAT?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Alternative A: Unconditional Artifact Overwrite                             │
│                                                                             │
│ - Implementation: Save model artifact automatically after training epoch.   │
│ - Advantages: Simple training script without evaluation gate logic.         │
│ - Disadvantages: Risk of deploying degraded models when training data is    │
│   noisy or sparse.                                                          │
│ - Complexity: Low.                                                          │
│ - Performance: Fast execution.                                              │
│ - Scalability: High.                                                        │
│ - Maintainability: Dangerous in automated cron/Airflow setups.              │
│ - Testability: Cannot verify deployment safety boundaries.                  │
│ - Operational Consequences: High risk of production prediction failures.    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Alternative B: Full MLOps Model Registry (MLflow / Sagemaker Registry)      │
│                                                                             │
│ - Implementation: Log models, register candidate versions, require manual   │
│   human approval via UI.                                                    │
│ - Advantages: Comprehensive lineage, audit history, multi-metric dashboard. │
│ - Disadvantages: Requires external database/server infrastructure and       │
│   human bottlenecks for routine periodic retraining.                        │
│ - Complexity: High.                                                         │
│ - Performance: Slower automated deployment cycles.                          │
│ - Scalability: Enterprise scale.                                            │
│ - Maintainability: Requires dedicated MLOps tool maintenance.               │
│ - Testability: Requires mocking registry APIs.                              │
│ - Operational Consequences: Overkill for single-node containerized engine.  │
└─────────────────────────────────────────────────────────────────────────────┘

```

### TRADEOFF

* **Gained:** Automated safety protection against degraded model deployments without requiring external MLOps registry infrastructure.


* **Sacrificed:** Model training runs take slightly longer because baseline predictions and evaluation metrics must be calculated across all folds.



### FAILURE POINT

If an unprecedented environmental catastrophe occurs (e.g., severe wildfire smoke), persistence baselines will have high error, but an ML model trained on historical data might also fail to clear the uplift threshold if its validation errors are equally high, preventing the model from adapting.

### CHANGE CONDITION

Adopting a full MLOps platform (e.g., MLflow, Weights & Biases) with multi-metric A/B canary testing infrastructure.

### SCALE CONDITION

Remains appropriate at any scale; compute overhead scales linearly with the number of validation folds.

### LEARNING QUESTION

> *Under what specific real-world atmospheric conditions would a naive Persistence model ($y_{t+h} = y_t$) legitimately outperform a trained LightGBM model for a 1-hour forecast horizon?*

---

## Comprehensive Summary Decision Matrix

| Architectural Decision | Implementation Location | Core Benefit | Main Sacrifice | Failure Condition |
| --- | --- | --- | --- | --- |
| **Hybrid Storage**<br> | `storage/db.py`, `storage/parquet_io.py`<br> | High columnar compression & fast scan performance

 | No atomic cross-store transactions

 | Concurrent uncoordinated worker writes

 |
| **SHA-256 Deduplication**<br> | `quality/hashing.py`, `quality/deduplication.py`<br> | Stateless, database-independent write idempotency

 | Per-record CPU hashing overhead

 | Unnormalized timestamp strings

 |
| **MAD Anomaly Detection**<br> | `analytics/anomaly.py`<br> | Robust against extreme outlier masking

 | Higher CPU sorting complexity ($\mathcal{O}(N \log N)$) | $>50\%$ identical values in window

 |
| **Purged Time-Series Split**<br> | `ml/split.py`<br> | Zero future temporal or lag data leakage

 | Discards boundary embargo data points

 | Lag features longer than embargo window

 |
| **Single-Source Feature Pipeline**<br> | `ml/features.py`<br> | Eliminates train-serve feature skew

 | Real-time feature compute on API requests

 | Historical fetch window smaller than max lag

 |
| **Quarantine Routing**<br> | `quality/validator.py`, `quality/quarantine.py`<br> | Isolates corrupt data without halting pipelines

 | JSONB PostgreSQL storage overhead

 | 100% data failure going unnoticed

 |
| **Baseline Uplift Gate**<br> | `ml/baselines.py`, `ml/training.py`<br> | Prevents deploying degraded ML models

 | Additional evaluation compute during training

 | Catastrophic non-stationary drift events

 |