# Comprehensive Feature-by-Feature Deep Dive: Air Quality Intelligence Engine (`aq_engine`)

---

# Feature 1: Multi-Source Resilient Ingestion & Connector Architecture

## 1. Feature Overview

* **What the feature does:** Connects to external third-party environmental web APIs (`OpenAQ` for air pollutant telemetry and `Open-Meteo` for meteorological observations/forecasts), retrieves time-series readings, and standardizes disparate payloads into unified internal representation schemas.


* **Who uses it:** Data engineers, automated schedulers (Apache Airflow), and operational CLI operators.


* **Problem it solves:** Upstream environmental APIs have differing pagination schemas, non-standard parameter names, strict rate limits, and transient HTTP instability (429 Rate Limit, 500/503 server errors).


* **Important business rules:**
1. Requests must enforce exponential backoff with jitter on network/server errors.


2. Pagination must exhaust available records up to a configured batch safety cap.


3. API-specific measurement units (e.g., ppm, ppb, $\mu\text{g/m}^3$) must be converted to standard SI metric units ($\mu\text{g/m}^3$, $^{\circ}\text{C}$, $\text{m/s}$, $\%$).



## 2. Entry Point

* **CLI Entry:** `src/aq_engine/cli.py` $\rightarrow$ `ingest(source: str, start_date: str, end_date: str)`

* **Airflow Entry:** `dags/aq_hourly_ingest_dag.py` $\rightarrow$ `PythonOperator(python_callable=run_hourly_ingest)`

* **Orchestrator Method:** `src/aq_engine/ingestion/orchestrator.py` $\rightarrow$ `IngestionOrchestrator.run()`


## 3. Complete Execution Trace

```
1. CLI / Airflow Trigger
   └─ File: src/aq_engine/cli.py -> def ingest()
      └─ Responsibility: Parse command-line args, initialize Config object, instantiate IngestionOrchestrator[cite: 1].
      └─ Input: source="openaq", start_date="2026-08-01", end_date="2026-08-02"
      └─ Output: Exit code 0 / Rich console output[cite: 1].

2. Orchestrator Coordination
   └─ File: src/aq_engine/ingestion/orchestrator.py -> IngestionOrchestrator.run()
      └─ Responsibility: Instantiate connector via factory, open run audit transaction in Postgres, orchestrate extraction[cite: 1].
      └─ Input: source_name, date_range
      └─ Side Effect: Inserts row into `ingestion_runs` table with status 'RUNNING'[cite: 1].

3. Connector Extraction
   └─ File: src/aq_engine/connectors/openaq.py -> OpenAQConnector.fetch_measurements()
      └─ File: src/aq_engine/connectors/base.py -> BaseConnector._execute_with_retry()
      └─ Responsibility: Send paginated HTTP GET requests with exponential backoff and rate limit pacing[cite: 1].
      └─ Input: HTTP endpoint URL, query params (location_id, date_from, date_to, limit=1000)[cite: 1].
      └─ Output: Raw JSON responses / list of raw dicts[cite: 1].

4. Connector Normalization
   └─ File: src/aq_engine/connectors/openaq.py -> OpenAQConnector._normalize_record()
      └─ Responsibility: Map provider JSON keys to `RawObservation` dataclass/Pydantic instances[cite: 1].
      └─ Input: Raw dict `{"parameter": "pm25", "value": 14.2, "date": {"utc": "..."}}`
      └─ Output: `List[RawObservation]`[cite: 1].

```

## 4. Data Flow

```
Upstream HTTP JSON Payload
  │ (Raw nested dicts from OpenAQ/Open-Meteo REST API)[cite: 1]
  ▼
Connector Model: RawObservation (src/aq_engine/connectors/models.py)
  │ Fields: location_id, parameter, value, unit, timestamp_utc, latitude, longitude[cite: 1]
  ▼
Standardized Ingestion DataFrame (pandas.DataFrame)
  │ Strict column typings: float64 values, timezone-aware datetime64[ns, UTC]
  ▼
Validation Ingress Model (src/aq_engine/quality/contracts.py)

```

## 5. Architecture

* **Controller:** `IngestionOrchestrator` governs the pipeline lifecycle and manages the execution state.


* **Connector Strategy:** `BaseConnector` defines the template method pattern for network operations with retry policies; `OpenAQConnector` and `OpenMeteoConnector` implement endpoint-specific parsing.


* **Infrastructure:** Synchronous HTTP client (`httpx` / `requests`) executing within containerized worker environments.



## 6. Design Decisions

* **Decision:** Base connector abstract base class with exponential backoff.


* *Why:* Isolates network volatility and rate-limiting mechanics away from domain data logic.


* *Alternatives:* Direct `requests.get` calls inside orchestrator or relying on third-party SDKs.
* *Tradeoffs:* Requires manual maintenance of connector models when upstream APIs release breaking schema revisions.





## 7. Failure Scenarios

* **HTTP 429 Rate Limit:** `_execute_with_retry` intercepts 429, reads `Retry-After` header (or defaults to exponential backoff), sleeps, and retries up to `max_retries` (default: 5).


* **API Offline / DNS Failure:** Retries exhausted $\rightarrow$ raises `ConnectorConnectionError` $\rightarrow$ orchestrator catches exception, updates `ingestion_runs.status = 'FAILED'`, and exits cleanly without committing corrupted state.



## 8. Security

* **Secrets Management:** Upstream API keys (`OPENAQ_API_KEY`) are read strictly from environment variables via `src/aq_engine/config.py`.


* **Header Injection:** API keys are injected via HTTP request headers rather than URL query parameters to avoid leaking credentials into server access logs.

## 9. Performance

* **Pagination Memory Guard:** Ingestion streams paginated batches directly into bounded memory chunks, avoiding memory blowup on multi-year extractions.
* **Network Latency:** Synchronous pagination creates I/O idle time during large backfills.



## 10. Testing

* **Unit Tests:** `tests/unit/test_openaq_connector.py`, `tests/unit/test_open_meteo_connector.py` mock HTTP endpoints via `responses` / `pytest-mock`.


* **Integration Tests:** `tests/integration/test_ingestion_orchestrator.py` verifies connector integration with the validation boundary.



---

# Feature 2: Data Quality, Schema Contracts & Cryptographic Deduplication

## 1. Feature Overview

* **What the feature does:** Enforces strict structural contracts, non-null guarantees, physical value boundaries, late-arrival policies, and SHA-256 natural-key content deduplication.


* **Who uses it:** Pipeline orchestrator (`IngestionOrchestrator`) and data quality auditors.


* **Problem it solves:** Sensor data frequently arrives corrupted, out-of-order, duplicated across repeated API queries, or with impossible values (e.g., negative pollutant concentrations, humidity $> 100\%$).


* **Important business rules:**
1. $\text{PM}_{2.5}$ must be bounded in $[0.0, 1000.0]\,\mu\text{g/m}^3$; $\text{PM}_{10}$ in $[0.0, 1500.0]\,\mu\text{g/m}^3$; relative humidity in $[0, 100]\%$.


2. Records sharing the same natural key tuple `(location_id, parameter, timestamp_utc)` must generate identical SHA-256 hashes and be deduplicated.


3. Records violating contracts or ranges must not crash the pipeline; they are routed to quarantine.





## 2. Entry Point

* **Module:** `src/aq_engine/quality/validator.py` $\rightarrow$ `DataQualityValidator.validate(df: pd.DataFrame)`


## 3. Complete Execution Trace

```
1. Validator Invocation
   └─ File: src/aq_engine/quality/validator.py -> DataQualityValidator.validate()
      └─ Responsibility: Evaluate DataFrame against structural contracts and validation rules[cite: 1].
      └─ Input: Raw ingestion `pd.DataFrame`
      └─ Output: `ValidationResult(valid_df=pd.DataFrame, quarantine_df=pd.DataFrame)`[cite: 1].

2. Schema & Type Enforcement
   └─ File: src/aq_engine/quality/contracts.py -> validate_schema_types()
      └─ Responsibility: Enforce column existence, float coercion, and UTC timestamp parsing[cite: 1].

3. Physical Range Rule Checks
   └─ File: src/aq_engine/quality/rules.py -> evaluate_physical_bounds()
      └─ Responsibility: Generate boolean bitmasks checking value bounds for each parameter[cite: 1].
      └─ Side Effect: Rows violating bounds get annotated with error codes (e.g., `ERR_VALUE_OUT_OF_BOUNDS`)[cite: 1].

4. Content Hash Generation
   └─ File: src/aq_engine/quality/hashing.py -> generate_record_hash()
      └─ Responsibility: Compute SHA-256 string across normalized `station_id|parameter|timestamp_utc`[cite: 1].
      └─ Output: 64-character hexadecimal hash string appended as `record_hash` column[cite: 1].

5. Deduplication
   └─ File: src/aq_engine/quality/deduplication.py -> deduplicate_records()
      └─ Responsibility: Keep latest record for duplicate `record_hash` within the batch and drop prior duplicates[cite: 1].

6. Quarantine Splitting
   └─ File: src/aq_engine/quality/quarantine.py -> QuarantineHandler.split()
      └─ Responsibility: Partition DataFrame into valid analytical rows and quarantined failure rows[cite: 1].

```

## 4. Data Flow

```
Raw Standardized DataFrame
  │
  ├─► [Schema & Bounds Validator] ──► Failed Rows ──► Quarantine DataFrame (with failure_reason, error_code)[cite: 1]
  │
  ▼ Passed Rows
[SHA-256 Hasher] (Natural key tuple hashed to record_hash column)[cite: 1]
  │
  ▼
[Deduplicator Engine] (df.drop_duplicates(subset=['record_hash']))[cite: 1]
  │
  ▼
Clean Analytical DataFrame (Ready for persistence)[cite: 1]

```

## 5. Architecture

* **Domain Layer:** `rules.py` and `contracts.py` encode pure business and physics logic without database dependencies.


* **Service Layer:** `DataQualityValidator` coordinates rules, hashing, and splitting.


* **Sink Layer:** `QuarantineHandler` translates rejected records into JSONB-ready database entities and quarantine Parquet files.



## 6. Design Decisions

* **Decision:** Cryptographic SHA-256 hashing for deduplication instead of database auto-incrementing surrogate keys.


* *Why:* Natural-key hashing enables deterministic, stateless deduplication across distributed workers and file-based Parquet storage without requiring an active database lock or central ID generator.


* *Alternatives:* Postgres `ON CONFLICT DO NOTHING` (fails when analytical storage is Parquet on disk).
* *Tradeoffs:* Slight CPU hashing overhead per record.





## 7. Failure Scenarios

* **Missing Column in Upstream Payload:** Caught during schema validation; the entire batch is marked invalid or individual rows missing mandatory keys are isolated to quarantine.


* **All Records In Batch Invalid:** Pipeline does not abort; valid DataFrame is returned empty ($N=0$), quarantine handler writes all rows to audit, and the ingestion run completes with status `WARNING` / `ZERO_VALID_ROWS`.



## 8. Security

* **Input Sanitization:** String inputs for station names, parameters, and error messages are cast and stripped to prevent malformed injections into relational tables or logging streams.



## 9. Performance

* **Vectorized Rule Evaluation:** Range and null checks are implemented using vectorized Pandas / NumPy boolean index operations ($\mathcal{O}(N)$) rather than Python row-by-row iteration loops.

## 10. Testing

* **Unit Tests:** `tests/unit/test_data_quality.py`, `tests/unit/test_quarantine.py`, `tests/unit/test_quality_complete.py` test invalid schemas, extreme values, and hash collision resistance.


* **Integration Tests:** `tests/integration/test_deduplication.py` and `tests/integration/test_idempotent_ingest.py` test end-to-end deduplication idempotency.



---

# Feature 3: Dual-Tier Hybrid Storage & Partitioned Parquet Lakehouse

## 1. Feature Overview

* **What the feature does:** Manages persistence across a dual-tier storage topology: PostgreSQL manages relational control-plane tables (stations, ingestion audits, sensor health, anomalies), while an Apache Parquet columnar data lake stores high-volume time-series facts.


* **Who uses it:** All subsystems (`ingestion`, `analytics`, `ml`, `api`).


* **Problem it solves:** Storing billions of immutable sensor telemetry rows in traditional relational databases leads to massive table bloat, slow analytical range scans, and high memory overhead.


* **Important business rules:**
1. Parquet files must be partitioned by `year=YYYY/month=MM/` (and optionally `station_id=...`) with Snappy compression.


2. Relational metadata tables must maintain foreign key integrity to the `stations` dimension.


3. Parquet reads must support partition pruning based on requested query time windows.





## 2. Entry Point

* **Relational Entry:** `src/aq_engine/storage/db.py` $\rightarrow$ `DatabaseManager`

* **Columnar Entry:** `src/aq_engine/storage/parquet_io.py` $\rightarrow$ `ParquetWriter` / `ParquetReader`


## 3. Complete Execution Trace

```
1. Write Ingress
   └─ File: src/aq_engine/storage/parquet_io.py -> ParquetWriter.write_hourly_facts()
      └─ Responsibility: Convert validated Pandas DataFrame to PyArrow Table, partition, and write to disk[cite: 1].
      └─ Input: `df: pd.DataFrame`, `base_dir: Path`
      └─ Output: List of written partition file paths[cite: 1].

2. PyArrow Partition Serialization
   └─ File: src/aq_engine/storage/parquet_io.py -> pyarrow.parquet.write_to_dataset()
      └─ Responsibility: Split records by partition columns `['year', 'month']`, compress using Snappy, write atomic `.parquet` files[cite: 1].
      └─ Side Effect: Creates directory structure `/data/processed/hourly_facts/year=2026/month=08/part_0.parquet`[cite: 1].

3. Relational Audit Commit
   └─ File: src/aq_engine/storage/db.py -> DatabaseManager.log_ingestion_run()
      └─ Responsibility: Record execution metrics in PostgreSQL[cite: 1].
      └─ Database Action: `INSERT INTO ingestion_runs (run_id, source_name, rows_ingested, status) VALUES (...)`[cite: 1].

```

## 4. Data Flow

```
Clean Ingestion DataFrame
  │
  ├─► PyArrow Table (pa.Table.from_pandas(df))[cite: 1]
  │     │
  │     ▼
  │   Partitioning Engine (split by year=YYYY / month=MM)[cite: 1]
  │     │
  │     ▼
  │   Disk Storage: /data/processed/hourly_facts/.../*.parquet[cite: 1]
  │
  └─► Relational Run Metadata ──► PostgreSQL ingestion_runs table[cite: 1]

```

## 5. Architecture

* **Relational Layer:** SQLAlchemy engine and session pool managing transactions against PostgreSQL.


* **Columnar Layer:** PyArrow dataset API executing fast columnar I/O, predicate pushdowns, and partition pruning.



## 6. Design Decisions

* **Decision:** Partitioning by `year` and `month`.


* *Why:* Balances file size against partition pruning granularity; avoids creating thousands of microscopic files (the "small file problem") while allowing fast annual/monthly partition dropping.


* *Alternatives:* Partitioning by `day` (creates too many tiny files) or no partitioning (forces full dataset scans).



## 7. Failure Scenarios

* **PostgreSQL Connection Lost:** `DatabaseManager` uses connection pool retries; if the database is unreachable, ingestion aborts before committing Parquet files to prevent orphaned un-audited datasets.


* **Disk Space Exhaustion during Parquet Write:** PyArrow raises `IOError` $\rightarrow$ transaction caught $\rightarrow$ marked as `FAILED` in logging.



## 8. Security

* **SQL Injection Prevention:** All SQL interactions in `db.py` use parameterized SQLAlchemy constructs or ORM queries.


* **Path Traversal Protection:** Directory paths constructed in `parquet_io.py` use Python's `pathlib.Path` with sanitized partition values.

## 9. Performance

* **Predicate Pushdown:** `ParquetReader` applies row-group filters at read time (e.g., `filters=[('parameter', '==', 'pm25')]`), scanning only relevant byte ranges.


* **Column Projection:** Queries select only necessary columns (e.g., `columns=['timestamp_utc', 'value']`), drastically reducing memory bandwidth.

## 10. Testing

* **Unit Tests:** `tests/unit/test_parquet_io.py`, `tests/unit/test_db.py` verify read/write cycles, schema preservation, and partition creation.


* **Integration Tests:** `tests/integration/test_hourly_facts.py` tests fact queries across multi-partition datasets.



---

# Feature 4: Analytics, Rolling Aggregations & Sensor Health Monitoring

## 1. Feature Overview

* **What the feature does:** Computes rolling multi-scale statistical aggregations (1h, 24h, 7d, 30d) and assesses sensor hardware reliability by detecting calibration drift, flatlining, and coverage degradation.


* **Who uses it:** Streamlit monitoring dashboard, sensor fleet maintenance engineers, downstream ML feature pipelines.


* **Problem it solves:** Physical air quality sensors experience hardware failures: they lose network connectivity (low coverage ratio), get stuck at fixed values (flatlining), or degrade over time (calibration drift).


* **Important business rules:**
1. Coverage ratio is defined as $\frac{N_{\text{actual}}}{N_{\text{expected}}}$ over a given time window; coverage $< 75\%$ flags degraded station health.


2. Flatline is detected if rolling standard deviation over $W \ge 6$ consecutive hours satisfies $\sigma < 10^{-6}$ while value $> 0$.


3. Calibration drift is detected if the rolling baseline median exhibits a monotonic directional shift exceeding the historical interquartile range (IQR).





## 2. Entry Point

* **CLI Entry:** `src/aq_engine/cli.py` $\rightarrow$ `health(station_id: str, window_days: int)`

* **Analytics Engine:** `src/aq_engine/analytics/station_health.py` $\rightarrow$ `StationHealthEvaluator.evaluate_station()`

* **Aggregation Engine:** `src/aq_engine/analytics/aggregation.py` $\rightarrow$ `AggregationEngine.compute_rolling_aggregations()`


## 3. Complete Execution Trace

```
1. Invocation & Data Loading
   └─ File: src/aq_engine/analytics/station_health.py -> StationHealthEvaluator.evaluate_station()
      └─ File: src/aq_engine/storage/parquet_io.py -> ParquetReader.load_station_window()
      └─ Responsibility: Load time-series slice for specified station across historical evaluation window[cite: 1].
      └─ Input: station_id="ST_DELHI_01", window_days=7
      └─ Output: `pd.DataFrame` indexed by `timestamp_utc`[cite: 1].

2. Coverage Ratio Calculation
   └─ File: src/aq_engine/analytics/station_health.py -> _compute_coverage()
      └─ Responsibility: Resample time series to 1-hour grid, count valid observations vs expected hourly grid slots[cite: 1].
      └─ Output: `coverage_ratio = actual_hours / total_expected_hours`[cite: 1].

3. Flatline Detection
   └─ File: src/aq_engine/analytics/station_health.py -> _detect_flatlines()
      └─ Responsibility: Compute rolling window standard deviation $\sigma_W$; flag sequences where $\sigma_W == 0.0$[cite: 1].
      └─ Output: `flatline_detected: bool`[cite: 1].

4. Drift Assessment
   └─ File: src/aq_engine/analytics/station_health.py -> _detect_drift()
      └─ Responsibility: Calculate Linear regression slope over rolling daily medians[cite: 1].
      └─ Output: `drift_detected: bool`[cite: 1].

5. Persistence
   └─ File: src/aq_engine/storage/db.py -> DatabaseManager.save_sensor_health_scorecard()
      └─ Responsibility: Insert evaluated health scorecard row into PostgreSQL `sensor_health` table[cite: 1].

```

## 4. Data Flow

```
Raw Hourly Fact Parquet Slices
  │
  ▼
Continuous 1-Hour Resampled Time-Series Grid (Missing hours represented as NaN)[cite: 1]
  │
  ├─► [Coverage Engine] ──────► coverage_ratio (float)[cite: 1]
  ├─► [Rolling Variance Engine] ─► flatline_flag (bool)[cite: 1]
  └─► [Linear Trend Evaluator] ──► drift_flag (bool)[cite: 1]
  │
  ▼
SensorHealthRecord (Pydantic / Relational Model) ──► PostgreSQL sensor_health[cite: 1]

```

## 5. Architecture

* **Analytics Layer:** Pure analytical algorithms operating on Pandas series and NumPy arrays (`aggregation.py`, `station_health.py`, `events.py`).


* **Persistence Integration:** Health evaluations write relational records to Postgres for fast dashboard querying.



## 6. Design Decisions

* **Decision:** Re-indexing to an explicit hourly frequency grid (`df.resample('1h')`) prior to health calculation.


* *Why:* Telemetry timestamps often arrive jittered by seconds/minutes (e.g., `10:01:14` vs `11:00:02`). Explicit grid snapping prevents false coverage drops.


* *Tradeoffs:* Requires defining deterministic timestamp alignment rules (e.g., round to nearest hour vs floor).



## 7. Failure Scenarios

* **Zero Observations in Window:** Resampled frame is entirely NaN $\rightarrow$ `coverage_ratio = 0.0`, `flatline_detected = False`, `drift_detected = False` $\rightarrow$ status recorded as `OFFLINE` without throwing division-by-zero errors.



## 8. Security

* Read-only analytical queries operate strictly on sanitized `station_id` identifiers; no dynamic unparameterized SQL strings are assembled.



## 9. Performance

* **Window Slicing Optimization:** Aggregations use native Pandas rolling window routines (`df.rolling('24h').mean()`), executed in optimized C/Cython loops.

## 10. Testing

* **Unit Tests:** `tests/unit/test_aggregation.py`, `tests/unit/test_station_health.py`, `tests/unit/test_analytics_complete.py` inject synthetic gaps, stuck constants, and linear ramps to verify detection accuracy.



---

# Feature 5: Statistical Anomaly Detection (Median Absolute Deviation)

## 1. Feature Overview

* **What the feature does:** Detects statistically anomalous pollutant spikes and episodic air pollution events using Median Absolute Deviation (MAD) rather than mean/variance filters.


* **Who uses it:** Alerting services, public health monitoring dashboards, API consumers.


* **Problem it solves:** Extreme air pollution events create massive outliers that heavily distort the empirical mean ($\mu$) and standard deviation ($\sigma$). Traditional $Z$-scores suffer from the "masking effect", where true anomalies escape detection because they artificially inflate $\sigma$.


* **Important business rules:**
1. For a window of observations $X$, compute median $\tilde{x} = \text{median}(X)$.


2. Compute $\text{MAD} = \text{median}(\vert{}x_i - \tilde{x}\vert{})$.


3. The modified $Z$-score is $M_i = \frac{0.6745 \cdot (x_i - \tilde{x})}{\text{MAD}}$ (or normalized with scale factor $1.4826$).


4. If $\vert{}M_i\vert{} > \text{threshold}$ (default: $3.5$), flag observation as an anomaly event and record it in PostgreSQL.





## 2. Entry Point

* **Module:** `src/aq_engine/analytics/anomaly.py` $\rightarrow$ `AnomalyDetector.detect_anomalies(df: pd.DataFrame, threshold: float = 3.5)`


## 3. Complete Execution Trace

```
1. Trigger Anomaly Evaluation
   └─ File: src/aq_engine/analytics/anomaly.py -> AnomalyDetector.detect_anomalies()
      └─ Responsibility: Compute rolling MAD statistics and extract anomaly rows[cite: 1].
      └─ Input: `df` containing columns `['station_id', 'parameter', 'value', 'timestamp_utc']`[cite: 1].
      └─ Output: `pd.DataFrame` of identified anomaly records with scores[cite: 1].

2. Windowed Median & MAD Computation
   └─ File: src/aq_engine/analytics/anomaly.py -> _compute_mad_scores()
      └─ Responsibility: Group by `['station_id', 'parameter']`, compute rolling median and rolling absolute deviation from median[cite: 1].

3. Modified Z-Score Thresholding
   └─ File: src/aq_engine/analytics/anomaly.py -> _filter_threshold()
      └─ Responsibility: Calculate modified Z-score $M_i$; apply boolean mask where $|M_i| > 3.5$[cite: 1].

4. Event Formatting & Relational Persistence
   └─ File: src/aq_engine/storage/db.py -> DatabaseManager.record_anomaly_events()
      └─ Responsibility: Persist flagged anomalies to PostgreSQL table `anomaly_events`[cite: 1].
      └─ Database Action: `INSERT INTO anomaly_events (station_id, parameter, observed_value, baseline_median, mad_score, detected_at) VALUES (...)`[cite: 1].

```

## 4. Data Flow

```
Time-Series Fact DataFrame
  │
  ▼
[Grouping Engine: (station_id, parameter)][cite: 1]
  │
  ▼
Rolling Median ($\tilde{x}$) & MAD Calculation ($\text{median}(|x_i - \tilde{x}|)$)[cite: 1]
  │
  ▼
Modified Z-Score Array ($M_i$)[cite: 1]
  │
  ▼
Filtered Anomaly DataFrame ($|M_i| > 3.5$)[cite: 1]
  │
  ▼
PostgreSQL Table: anomaly_events[cite: 1]

```

## 5. Architecture

* **Algorithmic Core:** `src/aq_engine/analytics/anomaly.py` contains non-parametric statistical implementations.


* **Architecture Decision Reference:** Formally documented in `docs/09-architecture-decisions/004-anomaly-detection-mad.md`.



## 6. Design Decisions

* **Decision:** MAD over Standard Deviation ($Z$-score).


* *Why:* The median and MAD are non-parametric order statistics with a high breakdown point ($50\%$), making them robust against massive pollution spikes that would distort parametric normal distributions.


* *Tradeoffs:* $\text{MAD} = 0$ if more than $50\%$ of values in a rolling window are identical (e.g., repeating zeroes); handled by falling back to a minimal $\epsilon$ floor to prevent division by zero.





## 7. Failure Scenarios

* **Zero Variance / Constant Sensor Signal:** If MAD evaluates to $0.0$, the denominator is clamped to $\epsilon = 1e-6$ to prevent zero-division runtime exceptions.



## 8. Security

* Anomaly metrics are internal numeric calculations without external code execution or dynamic query assembly risks.



## 9. Performance

* Computation is executed in vector space using NumPy array transformations per station-parameter partition.



## 10. Testing

* **Unit Tests:** `tests/unit/test_anomaly_detection.py` tests outlier injection, zero-MAD stability, and threshold boundary edge cases.



---

# Feature 6: Machine Learning Forecasting Pipeline & Leak-Free Time-Series Split

## 1. Feature Overview

* **What the feature does:** Trains, evaluates, and deploys gradient-boosted tree models (LightGBM) to forecast air pollutant concentrations ($\text{PM}_{2.5}$, $\text{PM}_{10}$) up to 24 hours into the future using temporal, atmospheric, and historical lag features.


* **Who uses it:** Automated retraining DAG (`dags/aq_model_retrain_dag.py`), CLI operators, and FastAPI forecast routes.


* **Problem it solves:** Standard cross-validation (e.g., $K$-Fold) randomly shuffles records across time, causing future data to leak into past training sets and producing overly optimistic evaluation metrics that fail in production.


* **Important business rules:**
1. Splitting must use expanding-window Purged Time-Series Cross-Validation with an embargo buffer.


2. Features must include cyclical temporal encodings ($\sin/\cos$ hour, day of week), autoregressive lags ($t-1, t-3, t-6, t-24$), and aligned weather features (temperature, wind speed, relative humidity).


3. A newly trained model must outperform naive persistence baselines (e.g., $y_{t+h} = y_t$) and rolling-mean baselines on Out-of-Fold RMSE/MAE to be promoted to production artifact status.





## 2. Entry Point

* **CLI Retrain Entry:** `src/aq_engine/cli.py` $\rightarrow$ `train(target: str, horizon: int)`

* **Airflow Retrain Entry:** `dags/aq_model_retrain_dag.py`

* **Core Trainer:** `src/aq_engine/ml/training.py` $\rightarrow$ `ModelTrainer.train()`


## 3. Complete Execution Trace

```
1. Ingress & Feature Dataset Assembly
   └─ File: src/aq_engine/ml/training.py -> ModelTrainer.train()
      └─ File: src/aq_engine/storage/parquet_io.py -> ParquetReader.load_ml_training_matrix()
      └─ Responsibility: Read historical pollutant facts and aligned weather facts from Parquet[cite: 1].
      └─ Output: Raw joined dataset DataFrame[cite: 1].

2. Feature Engineering Pipeline
   └─ File: src/aq_engine/ml/features.py -> FeaturePipeline.transform()
      └─ Responsibility: Assemble lag terms, rolling window averages/std-devs, and cyclical time sine/cosine encodings[cite: 1].
      └─ Input: Joined DataFrame
      └─ Output: Feature matrix $X$ and target vector $y$[cite: 1].

3. Purged Time-Series Splitting
   └─ File: src/aq_engine/ml/split.py -> TimeSeriesSplitter.split()
      └─ Responsibility: Generate chronologically sequential train/validation index folds with an embargo margin[cite: 1].
      └─ Output: Generator yielding `(train_idx, val_idx)` tuples[cite: 1].

4. Baseline Evaluation Gate
   └─ File: src/aq_engine/ml/baselines.py -> BaselineEvaluator.evaluate()
      └─ Responsibility: Compute RMSE, MAE, and WAPE for Persistence and 24h-Rolling-Mean baselines[cite: 1].
      └─ Output: Baseline metrics dictionary[cite: 1].

5. Model Fitting & Cross-Validation
   └─ File: src/aq_engine/ml/training.py -> ModelTrainer._fit_lightgbm()
      └─ Responsibility: Train LightGBM regressor with early stopping across validation folds[cite: 1].

6. Uplift Gate & Artifact Persistence
   └─ File: src/aq_engine/ml/training.py -> ModelTrainer._save_artifact()
      └─ Responsibility: Verify model $\text{RMSE} < \text{Baseline RMSE}$; serialize model booster to disk (`models/lgbm_pm25.booster`)[cite: 1].

```

## 4. Data Flow

```
Historical Facts (Air Quality + Weather Parquet)[cite: 1]
  │
  ▼
[Feature Pipeline] (Lags: t-1..t-24, Rolling: 6h/24h, Sin/Cos time)[cite: 1]
  │
  ▼
Feature Matrix X (N x D), Target Vector y (N)[cite: 1]
  │
  ▼
[Purged Time-Series Splitter] ──► Folds: Train [t_0 .. t_k], Embargo, Val [t_{k+e} .. t_m][cite: 1]
  │
  ▼
[LightGBM Regressor Fit] ──► Validation Predictions ──► Evaluation Metrics[cite: 1]
  │
  ▼ (If Uplift > Baselines)
Model Artifact (Binary Booster file saved to disk)[cite: 1]

```

## 5. Architecture

* **Feature Engineering:** Decoupled in `features.py` so identical transformation logic is executed by `ModelTrainer` during training and `InferenceEngine` during production inference.


* **Model Abstraction:** Wraps LightGBM with scikit-learn compatible estimator conventions.



## 6. Design Decisions

* **Decision:** Purged Time-Series Cross-Validation with Embargo.


* *Why:* Standard time splits can still leak information if autoregressive lag features span across the boundary between train and validation sets. The embargo buffer eliminates boundary overlap.


* *Tradeoffs:* Discards a small window of data points adjacent to the train-test split boundary.





## 7. Failure Scenarios

* **Model Underperforms Baseline:** If LightGBM fails to beat naive persistence, `ModelTrainer` raises `ModelUpliftValidationError`, rejects artifact promotion, and preserves the existing production model file.



## 8. Security

* Model artifacts are saved as native binary booster formats rather than unverified Python `pickle` objects, mitigating arbitrary code execution risks during artifact deserialization.



## 9. Performance

* LightGBM uses histogram-based feature binning and multi-threaded CPU parallelization for fast gradient-boosted tree construction.



## 10. Testing

* **Unit Tests:** `tests/unit/test_time_series_split.py`, `tests/unit/test_feature_engineering.py`, `tests/unit/test_model_training.py`, `tests/unit/test_inference.py`, `tests/unit/test_baselines.py`.


* **Performance Tests:** `tests/performance/test_ml_performance.py` measures training and inference latency limits.



---

# Feature 7: Consumption REST API & Operational CLI

## 1. Feature Overview

* **What the feature does:** Exposes high-throughput HTTP REST endpoints (FastAPI) and an interactive command-line interface (Typer/Rich) for querying station observations, running forecasts, inspecting sensor health scorecards, and checking platform health.


* **Who uses it:** External API clients, downstream dashboards (Streamlit), platform reliability engineers.


* **Problem it solves:** Provides uniform, validated, and documented query interfaces over the hybrid storage lakehouse and ML models without exposing raw database connections or file systems directly to clients.


* **Important business rules:**
1. API responses must conform to OpenAPI / JSON Schema contracts.


2. Unrecognized station identifiers must return standard HTTP 404 Not Found responses with descriptive JSON error bodies.


3. Forecast endpoints must return predicted hourly mean values along with prediction timestamps.





## 2. Entry Point

* **FastAPI Application:** `src/aq_engine/api/main.py` $\rightarrow$ `app = FastAPI(...)`

* **FastAPI Observations Router:** `src/aq_engine/api/observations.py`

* **CLI Application:** `src/aq_engine/cli.py` $\rightarrow$ `app = typer.Typer(...)`


## 3. Complete Execution Trace

```
1. Client Request Arrival
   └─ File: src/aq_engine/api/main.py -> ASGI Pipeline
      └─ Responsibility: Route HTTP GET /api/v1/observations/{station_id}[cite: 1]
      └─ Input: HTTP Headers, Path Parameter `station_id="ST_001"`, Query Parameter `hours=24`[cite: 1].

2. Router Handling & Parameter Validation
   └─ File: src/aq_engine/api/observations.py -> get_station_observations()
      └─ Responsibility: Validate types via Pydantic; invoke storage reader[cite: 1].

3. Columnar Data Scan
   └─ File: src/aq_engine/storage/parquet_io.py -> ParquetReader.get_recent_observations()
      └─ Responsibility: Execute partition-pruned scan across Parquet files for the station and time window[cite: 1].
      └─ Output: `List[ObservationRecord]`[cite: 1].

4. Response Serialization
   └─ File: src/aq_engine/api/observations.py -> Response Model
      └─ Responsibility: Serialize internal records into `StationObservationsResponse` Pydantic DTO[cite: 1].
      └─ Output: HTTP 200 OK + JSON Payload[cite: 1].

```

## 4. Data Flow

```
HTTP Request GET /api/v1/observations/ST_001?hours=24
  │
  ▼
FastAPI Query Parameter Parsing (station_id: str, hours: int)[cite: 1]
  │
  ▼
ParquetReader.get_recent_observations(station_id, hours)[cite: 1]
  │
  ▼
List[ObservationRecord] (Internal Domain Representation)[cite: 1]
  │
  ▼
Pydantic Response DTO: StationObservationsResponse[cite: 1]
  │
  ▼
HTTP 200 JSON Serialized Response

```

## 5. Architecture

* **Presentation Tier:** FastAPI ASGI application exposing asynchronous route handlers.


* **CLI Tier:** Typer wrapper exposing pipeline triggers, backfills, and health inspections as terminal commands.


* **Service Tier:** Direct integration with `storage.parquet_io`, `storage.db`, and `ml.inference`.



## 6. Design Decisions

* **Decision:** FastAPI with automatic OpenAPI generation.


* *Why:* Native async support, high throughput, and automatic Pydantic request/response schema validation and interactive Swagger documentation (`/docs`).





## 7. Failure Scenarios

* **Non-existent Station ID:** Storage layer returns empty dataset $\rightarrow$ route raises `HTTPException(status_code=404, detail="Station not found")`.


* **Internal Engine Crash:** Caught by FastAPI global exception handler $\rightarrow$ returns structured HTTP 500 JSON error without leaking stack traces.



## 8. Security

* **CORS Middleware:** Configured in `src/aq_engine/api/main.py` with explicit allowed origins.


* **Parameter Validation:** Pydantic strictly validates types and query bounds (e.g., $1 \le \text{hours} \le 720$), mitigating Denial-of-Service attacks from oversized range requests.



## 9. Performance

* Read-only observation queries bypass PostgreSQL completely, querying pre-aggregated Parquet data files directly with zero database lock contention.



## 10. Testing

* **Unit Tests:** `tests/unit/test_api_observations.py`, `tests/unit/test_api_health.py`, `tests/unit/test_api_forecast_events.py`, `tests/unit/test_cli.py` use `TestClient` and `CliRunner`.


* **Performance Tests:** `tests/performance/test_api_performance.py` measures response latency under concurrent load.



---

# Architecture Comparisons & Alternative Designs

| Criterion | Current Design (Dual-Tier Hybrid: Postgres + Parquet) | Alternative 1: Monolithic Relational (Pure PostgreSQL / TimescaleDB) | Alternative 2: Distributed Cloud Analytics (ClickHouse / Snowflake) |
| --- | --- | --- | --- |
| **System Complexity** | Medium (requires managing both DB and file directory storage)

 | **Low** (Single database engine for all data) | High (Requires dedicated distributed analytical cluster) |
| **Storage Cost** | **Lowest** (Parquet columnar compression on local disk / S3)

 | High (Uncompressed/row storage creates massive table bloat) | Medium-High (Cloud warehouse operational and compute costs) |
| **Scan Performance** | **Fast** (Columnar reads with partition pruning)

 | Moderate to Slow on multi-million row aggregations | **Extremely Fast** (Massively parallel vector query engines) |
| **Write Idempotency** | Stateless SHA-256 natural key hash checking

 | Database Unique Constraints (`ON CONFLICT DO NOTHING`) | Deduplication via ReplacingMergeTree / Materialized views |
| **Operational Simplicity** | **High** (Self-contained in Docker Compose; zero external managed services)

 | **High** (Single connection string, straightforward backups) | Low (Requires complex infrastructure and distributed cluster ops) |

---

# Implementation Exercise: Build a Custom Quality Rule & Sensor Anomaly Evaluator

### Objective

Implement a custom validation rule and statistical spike detector for Sulphur Dioxide ($\text{SO}_2$) telemetry inside the `aq_engine` framework.

### Specifications

1. **Rule Logic:** Open `src/aq_engine/quality/rules.py`. Create a function `validate_so2_range(df: pd.DataFrame) -> pd.DataFrame` that flags any observation where $\text{SO}_2 < 0.0\,\mu\text{g/m}^3$ or $\text{SO}_2 > 2000.0\,\mu\text{g/m}^3$ with the error code `ERR_SO2_OUT_OF_RANGE`.


2. **Deduplication:** Ensure your function preserves the `record_hash` generated in `src/aq_engine/quality/hashing.py`.


3. **MAD Evaluation:** Write a function inside `src/aq_engine/analytics/anomaly.py` named `evaluate_so2_spikes(df: pd.DataFrame, window_hours: int = 12)` that calculates the rolling MAD of $\text{SO}_2$ and returns all records where the modified $Z$-score $M_i > 4.0$.



---

# Learning Curriculum Questions

### Beginner Questions

1. What are the two primary external data sources ingested by `aq_engine`?


2. In which module is the command-line interface implemented?


3. Which file formats are used for relational metadata versus time-series fact storage?


4. How are timestamps formatted and standardized across all engine components?


5. What is the role of `BaseConnector` in `src/aq_engine/connectors/base.py`?


6. What HTTP library does the platform use to fetch upstream web API data?


7. Where are runtime database connection parameters defined?


8. What happens when an invalid observation is encountered during ingestion?


9. Which web framework powers the REST API?


10. Name the CLI command used to trigger a manual data ingestion run.



### Intermediate Questions

11. How does the SHA-256 record hashing mechanism guarantee ingestion idempotency?


12. Why is Parquet storage partitioned by `year` and `month` rather than a single flat file?


13. What statistical formula is used to calculate the Median Absolute Deviation (MAD)?


14. Why is the rolling standard deviation used to detect sensor flatlining?


15. How does `StationHealthEvaluator` compute the coverage ratio of a station?


16. What is the difference between `dags/aq_hourly_ingest_dag.py` and `dags/aq_daily_backfill_dag.py`?


17. How does the `FeaturePipeline` encode cyclical temporal features like the hour of the day?


18. What relational table stores the execution history of ingestion jobs?


19. How does `ParquetReader` prune partitions when querying a specific date window?


20. Why does `ModelTrainer` evaluate models against persistence baselines before saving artifacts?



### Advanced Questions

21. Explain the "masking effect" in outlier detection and why MAD is immune to it while standard $Z$-score is not.


22. How does Purged Time-Series Cross-Validation with an embargo buffer prevent data leakage?


23. Why is saving LightGBM models in native binary booster format safer than using Python `pickle`?


24. What concurrency failure mode could occur if two workers write to the same Parquet partition simultaneously?


25. How would you refactor `src/aq_engine/connectors/base.py` to use asynchronous HTTP requests (`httpx.AsyncClient`)?


26. What are the tradeoffs of storing malformed payloads as `JSONB` in the `quarantine_records` table?


27. How does predicate pushdown in PyArrow reduce memory usage during historical observation queries?


28. What happens to MAD anomaly detection if more than $50\%$ of values in a rolling window are identical?


29. Describe how the system maintains feature alignment between air quality measurements and meteorological features.


30. If you migrated the analytical store from Parquet to ClickHouse, which engine classes would need to be modified?



---

# Answer Key

1. **OpenAQ** (pollutants) and **Open-Meteo** (weather).


2. `src/aq_engine/cli.py`.


3. **PostgreSQL** for relational metadata and **Apache Parquet** for time-series facts.


4. Timezone-aware ISO-8601 UTC datetimes (`datetime64[ns, UTC]`).


5. It provides common HTTP retry logic, exponential backoff, rate limiting, and pagination handling.


6. `httpx` / `requests`.


7. `configs/base.yaml`, `configs/default.yaml`, and `src/aq_engine/config.py` (via `.env` variables).


8. It is annotated with an error code and routed to the quarantine storage layer.


9. **FastAPI**.


10. `aq ingest` (or `python -m aq_engine.cli ingest`).


11. It deterministically hashes the composite natural key `(location_id, parameter, timestamp_utc)`. Identical payloads yield identical hashes, allowing duplicate rows to be identified and dropped prior to persistence.


12. To prevent file bloat while enabling partition pruning, allowing the reader to skip entire directory trees for unqueried months.


13. $\text{MAD} = \text{median}(\vert{}x_i - \text{median}(X)\vert{})$.


14. A functional sensor exhibits natural micro-variations. If $\sigma_W \approx 0.0$ over several hours, the sensor hardware or ADC is stuck at a constant value.


15. By dividing the number of actual hourly readings received by the total expected hourly slots in the evaluated time window.


16. The hourly DAG ingests recent sliding increments ($1\text{h}$), while the backfill DAG processes multi-day/multi-month historical date ranges with partition re-alignment.


17. Using sine and cosine transformations: $\sin\left(\frac{2\pi \cdot \text{hour}}{24}\right)$ and $\cos\left(\frac{2\pi \cdot \text{hour}}{24}\right)$.


18. `ingestion_runs` in PostgreSQL.


19. It constructs directory path filters corresponding to the `year=YYYY/month=MM/` partition hierarchy, reading only matching directories.


20. To verify that the ML model provides actual predictive uplift over simple persistence ($y_{t+h} = y_t$) before deploying it.


21. In severe pollution events, extreme values inflate the sample mean $\mu$ and standard deviation $\sigma$, which reduces standard $Z$-scores and hides anomalies. MAD uses the median, which has a 50% breakdown point and is resistant to outlier distortion.


22. Autoregressive features create dependencies across adjacent timestamps. Purging removes test-overlapping samples, and the embargo buffer discards training samples immediately preceding validation sets to eliminate temporal leakage.


23. `pickle` allows arbitrary Python object instantiation and can execute malicious shell payloads upon deserialization. Native booster files serialize only model tree structures and weights.


24. A race condition could result in one worker overwriting the partition file of another, causing data loss without an atomic rename or file locking mechanism.


25. Replace synchronous `requests.get` with `async with httpx.AsyncClient() as client: await client.get(...)` and convert connector methods to asynchronous coroutines (`async def`).


26. **Advantage:** Preserves malformed payloads with arbitrary schema deviations without causing database insertion crashes. **Tradeoff:** Higher JSON storage footprint in PostgreSQL.


27. Predicate pushdown pushes filter expressions down to the PyArrow Parquet reader, scanning and decoding only matching byte ranges and columns from disk.


28. $\text{MAD}$ evaluates to $0.0$, which would cause division-by-zero errors. The engine handles this by applying an $\epsilon$ floor (e.g., $10^{-6}$).


29. By rounding measurements to a common hourly UTC grid and performing an equi-join on `(location_id, timestamp_utc)`.


30. `src/aq_engine/storage/parquet_io.py` and `src/aq_engine/storage/db.py` would be replaced by a unified ClickHouse client interface (e.g., `clickhouse-connect`), while analytics and ML modules would update their data loading queries.