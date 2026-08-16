Here is the complete set of architecture diagrams and accompanying analyses reverse-engineered directly from the repository.

---

## 1. System Context Diagram

```mermaid
flowchart TB
    subgraph Users["Actors & Consumers"]
        DataEngineer["Data Engineer / Operator\n(CLI / Airflow UI)"]
        DashboardUser["Analyst / Stakeholder\n(Streamlit UI)"]
        APIClient["Downstream Application / Consumer\n(HTTP REST Client)"]
    end

    subgraph SystemBoundary["Air Quality Intelligence Engine (aq_engine)"]
        CoreSystem["Air Quality Intelligence Platform\n(Ingestion, Quality, Analytics, ML, API)"]
    end

    subgraph ExternalSystems["External Upstream APIs"]
        OpenAQ["OpenAQ API\n(v2 / v3 Endpoints)"]
        OpenMeteo["Open-Meteo API\n(Historical & Forecast Weather)"]
    end

    subgraph DataStorage["Data Stores"]
        PostgresDB[("PostgreSQL Control Plane\n(Stations, Runs, Sensor Health, Anomalies)")]
        ParquetLake[("Partitioned Parquet Data Lake\n(Hourly Facts, Raw, Quarantine)")]
    end

    DataEngineer -->|"Triggers runs, backfills, retraining via CLI/DAGs"| CoreSystem
    DashboardUser -->|"Views health scorecards, anomalies, analytics"| CoreSystem
    APIClient -->|"Queries observations, forecasts, alerts"| CoreSystem

    CoreSystem -->|"Fetches pollutant measurements"| OpenAQ
    CoreSystem -->|"Fetches meteorological features"| OpenMeteo

    CoreSystem <-->|"Reads/Writes metadata, runs, audits, health"| PostgresDB
    CoreSystem <-->|"Reads/Writes time-series facts, raw batches"| ParquetLake

```

### How to read this diagram

This diagram shows the system boundary of `aq_engine`, its primary human and machine actors, the external web APIs it pulls from, and the two data stores it persists information into.

### Important observations

* **Dual Ingestion Sources:** The system couples pollutant data with meteorological conditions from separate upstream providers (`OpenAQ` and `Open-Meteo`).


* **Hybrid Storage Separation:** Analytical time-series facts are decoupled from relational state and transactional execution logs.


* **Multiple Consumption Interfaces:** Interaction happens via REST APIs, analytical dashboards, or direct operator CLI commands.



### Questions to ask yourself

1. Why does the system separate metadata into PostgreSQL and time-series data into Parquet?
2. What happens to the system if Open-Meteo is unavailable while OpenAQ is healthy?
3. Which actors trigger batch processing versus real-time queries?
4. How do downstream API clients authenticate when querying endpoints?
5. Where does human intervention occur during data quarantine events?

---

## 2. Container Diagram

```mermaid
flowchart TB
    subgraph ClientTier["Clients"]
        Browser["Web Browser"]
        Terminal["Operator Terminal"]
    end

    subgraph ContainerEnvironment["Docker Compose / Container Host"]
        APIContainer["Container: FastAPI Server\n(src/aq_engine/api)\n(Port 8000)"]
        DashboardContainer["Container: Streamlit Dashboard\n(Port 8501)"]
        WorkerContainer["Container: Worker / CLI / Orchestrator\n(aq_engine CLI & Ingestion Engine)"]
        
        subgraph Databases["Persistent Storage"]
            PostgresContainer[("Container: PostgreSQL 15+\n(Port 5432)")]
            StorageVolume[("Local / Mounted File System\n(/data/raw, /data/processed, /data/quarantine)")]
        end
    end

    subgraph OrchestratorTier["Airflow Scheduling Layer"]
        AirflowScheduler["Airflow Scheduler / DAGs\n(dags/aq_hourly_ingest_dag.py\ndags/aq_daily_backfill_dag.py\ndags/aq_model_retrain_dag.py)"]
    end

    subgraph ExternalAPIs["External Services"]
        ExtOpenAQ["api.openaq.org"]
        ExtOpenMeteo["archive-api.open-meteo.com"]
    end

    Browser -->|"HTTP :8501"| DashboardContainer
    Browser -->|"HTTP :8000"| APIContainer
    Terminal -->|"CLI command execution"| WorkerContainer

    AirflowScheduler -->|"Triggers ingestion & retraining"| WorkerContainer

    DashboardContainer -->|"HTTP GET"| APIContainer
    APIContainer -->|"SQL Queries"| PostgresContainer
    APIContainer -->|"PyArrow Scans"| StorageVolume

    WorkerContainer -->|"HTTPS GET"| ExtOpenAQ
    WorkerContainer -->|"HTTPS GET"| ExtOpenMeteo
    WorkerContainer -->|"SQL Read/Write"| PostgresContainer
    WorkerContainer -->|"Parquet Read/Write"| StorageVolume

```

### How to read this diagram

This diagram details the runtime containers specified in `docker-compose.yml` and the Dockerfiles (`Dockerfile.api`, `Dockerfile.dashboard`, `Dockerfile.worker`), showing how network requests flow between services, shared volumes, and database ports.

### Important observations

* **Decoupled API and Dashboard:** Streamlit runs in a dedicated container and queries FastAPI / storage rather than embedding pipeline ingestion directly.


* **Shared Storage Volume:** The Parquet Lakehouse relies on a mounted directory accessible by both the Worker (for writes) and the API (for analytical reads).


* **No Distributed Message Queue:** *Observable Fact:* The repository does not include RabbitMQ, Kafka, or Redis in its Compose definitions; Airflow and cron/CLI act as the execution dispatchers.



### Questions to ask yourself

1. If the Parquet store is on a mounted volume, what happens when scaling the API container across multiple hosts?
2. How does the worker container coordinate simultaneous writes to Parquet files?
3. What mechanism notifies the API when new data is committed to the file system?
4. How do health checks in `docker/health-check.sh` determine if the API container is ready to receive traffic?


5. Why is Streamlit separated from FastAPI rather than serving static frontend assets directly from FastAPI?

---

## 3. Component Diagram

```mermaid
flowchart TB
    subgraph IngestionSubsystem["1. Ingestion Subsystem (src/aq_engine/ingestion & connectors)"]
        BaseConn["BaseConnector\n(Retry, Backoff, Paging)"]
        OpenAQConn["OpenAQConnector"]
        OpenMeteoConn["OpenMeteoConnector"]
        IngestOrch["IngestionOrchestrator"]
        
        OpenAQConn --|> BaseConn
        OpenMeteoConn --|> BaseConn
        IngestOrch --> OpenAQConn
        IngestOrch --> OpenMeteoConn
    end

    subgraph QualitySubsystem["2. Quality & Validation Subsystem (src/aq_engine/quality)"]
        DataContracts["Data Contracts & Pydantic Models"]
        DQValidator["DataQualityValidator"]
        HashDeduper["ContentHasher & Deduplicator\n(SHA-256)"]
        Quarantine["QuarantineHandler"]
        
        DQValidator --> DataContracts
        DQValidator --> HashDeduper
        DQValidator --> Quarantine
    end

    subgraph StorageSubsystem["3. Storage Subsystem (src/aq_engine/storage)"]
        DBMgr["DatabaseManager\n(SQLAlchemy/PostgreSQL)"]
        ParquetIO["ParquetIO\n(PyArrow Partition Writer/Reader)"]
    end

    subgraph AnalyticsSubsystem["4. Analytics Subsystem (src/aq_engine/analytics)"]
        AggEngine["AggregationEngine\n(1h, 24h, 7d, 30d)"]
        AnomalyDet["AnomalyDetector\n(MAD Statistical Filter)"]
        HealthEval["StationHealthEvaluator\n(Drift, Flatline, Coverage)"]
        EventDet["EventDetector\n(Acute Episodes)"]
    end

    subgraph MLSubsystem["5. ML & Forecasting Subsystem (src/aq_engine/ml)"]
        TimeSplit["TimeSeriesSplitter\n(Expanding Window, Purged CV)"]
        FeatEng["FeaturePipeline\n(Lags, Rolling, Temporal)"]
        ModelTrainer["ModelTrainer\n(LightGBM / Baselines)"]
        InferEngine["InferenceEngine"]
        
        ModelTrainer --> TimeSplit
        ModelTrainer --> FeatEng
        InferEngine --> FeatEng
    end

    subgraph APISubsystem["6. API Subsystem (src/aq_engine/api)"]
        FastAPIRouter["FastAPI Application & Routers"]
        ObsRouter["Observations & Forecast Routes"]
        HealthRouter["System & Sensor Health Routes"]
        
        FastAPIRouter --> ObsRouter
        FastAPIRouter --> HealthRouter
    end

    %% Cross Subsystem Relationships
    IngestOrch --> DQValidator
    IngestOrch --> DBMgr
    IngestOrch --> ParquetIO
    
    DQValidator -.->|"Invalid rows"| Quarantine
    Quarantine --> DBMgr
    Quarantine --> ParquetIO

    AnalyticsSubsystem --> ParquetIO
    AnalyticsSubsystem --> DBMgr

    MLSubsystem --> ParquetIO
    
    ObsRouter --> ParquetIO
    ObsRouter --> InferEngine
    HealthRouter --> DBMgr

```

### How to read this diagram

This diagram opens up the `src/aq_engine/` directory to show the internal modular structure across its six core packages and how objects interact across domain boundaries.

### Important observations

* **Ingestion Orchestrator as Controller:** `IngestionOrchestrator` controls fetching, runs validation, routes invalid records to quarantine, and commits valid rows to storage.


* **Feature Pipeline Symmetry:** `FeaturePipeline` is shared between `ModelTrainer` (for training set preparation) and `InferenceEngine` (for online/batch scoring), preventing train-serve feature skew.


* **Decoupled Analytics:** Statistical analysis (MAD and sensor health) runs over committed storage slices rather than running inside the raw network ingestion stream.



### Questions to ask yourself

1. Which component is responsible for determining if a sensor is suffering from flatline drift?
2. How does the `QuarantineHandler` ensure invalid rows do not contaminate the analytics dataset?
3. How does `TimeSeriesSplitter` prevent temporal leakage when evaluating models?
4. What interface must a new connector implement to add a third environmental data source?
5. Why are aggregations calculated in a dedicated module rather than via SQL database views?

---

## 4. Dependency Diagram

```mermaid
flowchart TD
    cli["src/aq_engine/cli.py"]
    api["src/aq_engine/api/"]
    dags["dags/ (Airflow DAGs)"]
    
    ingestion["src/aq_engine/ingestion/"]
    ml["src/aq_engine/ml/"]
    analytics["src/aq_engine/analytics/"]
    quality["src/aq_engine/quality/"]
    storage["src/aq_engine/storage/"]
    connectors["src/aq_engine/connectors/"]
    
    config["src/aq_engine/config.py"]
    common["src/aq_engine/common/\n(exceptions, logger, time)"]

    cli --> ingestion
    cli --> ml
    cli --> analytics
    cli --> storage
    cli --> config

    dags --> ingestion
    dags --> ml
    dags --> analytics

    api --> storage
    api --> analytics
    api --> ml
    api --> config
    api --> common

    ingestion --> connectors
    ingestion --> quality
    ingestion --> storage
    ingestion --> common
    ingestion --> config

    ml --> storage
    ml --> common
    ml --> config

    analytics --> storage
    analytics --> common
    analytics --> config

    quality --> common
    quality --> config

    connectors --> common
    connectors --> config

    storage --> common
    storage --> config

```

### How to read this diagram

Arrows represent direct Python `import` statements. Packages higher in the diagram depend on lower-level infrastructure and domain packages. `common` and `config` are foundational utility layers.

### Important observations

* **Acyclic Architecture:** The import graph is strictly directed and acyclic (DAG structure), with no circular imports between `analytics`, `ml`, and `ingestion`.


* **Independent Leaf Nodes:** `connectors` and `quality` do not depend on `storage` or `analytics`, allowing them to be unit tested in isolation without mocking databases.


* **Shared Foundations:** `common` (custom exceptions, structured logging, UTC timestamp utilities) and `config` are imported across all modules.



### Questions to ask yourself

1. Can you test `src/aq_engine/quality/validator.py` without spinning up a PostgreSQL instance?
2. If `src/aq_engine/storage/parquet_io.py` changes its schema, which upstream modules are directly affected?
3. Why don't connectors import the storage layer?
4. What prevents circular dependencies between the ML feature generation module and the analytical aggregation module?
5. How is runtime configuration propagated to deeply nested connectors?

---

## 5. Request Lifecycle (FastAPI Observations & Forecasts)

```mermaid
flowchart TD
    ClientReq["1. Client HTTP GET /api/v1/observations/stations/{id}/forecast"]
    
    FastAPIMw["2. FastAPI Middleware & Exception Handlers\n(Request timing, CORS, Error interception)"]
    
    RouteValidation["3. Parameter Validation via Pydantic\n(station_id: str, horizon_hours: int = 24)"]
    
    Handler["4. Route Handler: aq_engine.api.observations.get_station_forecast()"]
    
    StorageFetch["5. ParquetIO / DatabaseManager Data Retrieval\n- Fetch recent 72h historical observations\n- Fetch aligned weather forecasts"]
    
    FeatGen["6. ML Feature Pipeline\n(Build lag terms, rolling means, temporal sine/cosine)"]
    
    ModelPredict["7. Inference Engine\n(LightGBM predict over generated feature matrix)"]
    
    ResponseFormat["8. Response Serialization\n(Pydantic ForecastResponse schema)"]
    
    ClientRes["9. HTTP 200 OK JSON Response"]

    ClientReq --> FastAPIMw
    FastAPIMw --> RouteValidation
    RouteValidation --> Handler
    Handler --> StorageFetch
    StorageFetch --> FeatGen
    FeatGen --> ModelPredict
    ModelPredict --> ResponseFormat
    ResponseFormat --> FastAPIMw
    FastAPIMw --> ClientRes

```

### How to read this diagram

This flow shows the end-to-end lifecycle of an HTTP forecast request from the moment it enters the ASGI web server until the JSON payload is returned to the client.

### Important observations

* **Real-time Feature Transformation:** Features for inference are assembled on the fly from stored historical lags and recent weather forecasts.


* **Type-Safe Ingress & Egress:** Pydantic models validate incoming query parameters and ensure serializable JSON schema adherence on exit.


* **In-Process Model Inference:** Model scoring runs directly inside the API process using the bundled LightGBM artifact.



### Questions to ask yourself

1. What error code is returned if `station_id` does not exist in the database?
2. How does the system handle predictions if recent weather data is missing from the Parquet store?
3. What performance bottleneck might arise during `StorageFetch` if historical Parquet partitions are fragmented?
4. How is the LightGBM model artifact loaded into memory (on startup vs. per-request)?
5. What HTTP response is returned if the ML inference pipeline fails unexpectedly?

---

## 6. Data Flow Diagram

```mermaid
flowchart LR
    subgraph External["External APIs"]
        RawOpenAQ["OpenAQ API"]
        RawOpenMeteo["Open-Meteo API"]
    end

    subgraph ExtractionStage["Stage 1: Extract & Transform"]
        RawExtract["Connectors (HTTP Raw Payloads)"]
        Standardize["Standardized Internal Records\n(Pydantic Raw Observation Model)"]
    end

    subgraph QualityStage["Stage 2: Validation & Deduplication"]
        Validator["Quality Gate\n(Rules, Ranges, Nulls)"]
        Hasher["SHA-256 Hashing\n(Hash = f(station, param, time))"]
        QuarantineBuffer["Quarantine Processor"]
    end

    subgraph StorageStage["Stage 3: Hybrid Persistence"]
        ParquetSink[("Parquet Lakehouse\n(/processed/hourly_facts)")]
        QuarantineSink[("Quarantine Store\n(PostgreSQL & /quarantine)")]
        PostgresAudit[("Control Plane\n(ingestion_runs, station_health)")]
    end

    subgraph ConsumptionStage["Stage 4: Analytics & Consumption"]
        AnalyticsWorker["Analytics & Anomaly Engine"]
        MLWorker["Model Retraining / Scoring"]
        APIOut["FastAPI REST Endpoints"]
    end

    RawOpenAQ --> RawExtract
    RawOpenMeteo --> RawExtract
    RawExtract --> Standardize
    Standardize --> Validator
    
    Validator -->|"Passed"| Hasher
    Validator -->|"Failed"| QuarantineBuffer
    
    QuarantineBuffer --> QuarantineSink
    
    Hasher -->|"Unique Valid Records"| ParquetSink
    Hasher -->|"Run Metadata & Counts"| PostgresAudit
    
    ParquetSink --> AnalyticsWorker
    ParquetSink --> MLWorker
    ParquetSink --> APIOut
    
    AnalyticsWorker -->|"Anomalies & Health"| PostgresAudit
    PostgresAudit --> APIOut

```

### How to read this diagram

This diagram traces raw data from external HTTP sources through validation, deduplication, persistent partitioned storage, and downstream analytics consumption.

### Important observations

* **Hard Quarantine Boundary:** Invalid records are branched off before reaching analytical Parquet partitions, ensuring clean downstream calculations.


* **Content Hashing:** Deduplication occurs in memory prior to disk write by evaluating the cryptographic hash of the record's natural key.


* **Separation of Fact and Anomaly Data:** Clean facts flow to Parquet; anomaly event flags and health metrics flow back to PostgreSQL.



### Questions to ask yourself

1. What fields comprise the composite natural key used for SHA-256 hashing?
2. If a quarantined record is later fixed, how is it re-ingested into the Parquet lakehouse?
3. How are late-arriving measurements processed if their partition month has already been written?
4. What happens when duplicate measurements with identical timestamps but differing pollutant values arrive?
5. How do dbt transformation models interact with the data written to the Parquet/Postgres layer?



---

## 7. Authentication & Authorization Flow

```mermaid
flowchart TD
    subgraph ObservableImplementation["Authentication Architecture (Derived from Codebase)"]
        Client["Client / Operator"]
        
        subgraph APIGateway["FastAPI Application Boundary"]
            Endpoint["API Endpoints / CLI Commands"]
            EnvConfig["Config Layer (src/aq_engine/config.py)\n- API Keys / DB Credentials via .env\n- Upstream API Keys (OpenAQ API Key)"]
        end
        
        subgraph AuthStatus["Current Repository Authentication State"]
            AuthCheck{"Is Internal API Auth Implemented?"}
            NoAuth["API Endpoints: Public / Unauthenticated\n(No JWT / OAuth2 / API Key Middleware on FastAPI)"]
            UpstreamAuth["Upstream API Auth: Outgoing Header Injection\n(X-API-Key: OPENAQ_API_KEY)"]
        end
    end

    Client --> Endpoint
    Endpoint --> AuthCheck
    AuthCheck -->|"FastAPI internal endpoints"| NoAuth
    AuthCheck -->|"Connectors calling OpenAQ"| UpstreamAuth
    EnvConfig --> UpstreamAuth

```

### How to read this diagram

This diagram reflects the **actual authentication mechanisms found in the repository** rather than an idealized standard pattern.

### Important observations

* **Explicit Fact — No Internal API Authentication:** *Observable from Code:* `src/aq_engine/api/main.py` and `observations.py` do not implement token verification, OAuth2, or session cookies. The REST API is designed for internal network or VPC deployment.


* **Outbound Connector Authentication:** `OpenAQConnector` reads `OPENAQ_API_KEY` from configuration and injects it into outgoing HTTP request headers.


* **Database Authentication:** Relational connections use PostgreSQL user/password credentials managed via environment variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`).



### Questions to ask yourself

1. What changes would be required to add OAuth2 / JWT bearer token validation to `src/aq_engine/api/main.py`?


2. How should API keys be rotated without restarting the container services?
3. What security risk exists when running FastAPI unauthenticated on a publicly exposed port?
4. How do CLI commands authenticate against the PostgreSQL database?


5. Where are secrets and credentials stored in production versus local development?



---

## 8. Database Entity-Relationship (ER) Diagram

```mermaid
erDiagram
    STATIONS ||--o{ SENSOR_HEALTH : "evaluates"
    STATIONS ||--o{ ANOMALY_EVENTS : "records"
    STATIONS ||--o{ QUARANTINE_RECORDS : "associates"
    INGESTION_RUNS ||--o{ QUARANTINE_RECORDS : "flags"

    STATIONS {
        varchar(64) id PK
        varchar(128) external_id
        varchar(255) name
        varchar(64) city
        varchar(64) country
        double_precision latitude
        double_precision longitude
        timestamp_tz created_at
        timestamp_tz updated_at
    }

    INGESTION_RUNS {
        varchar(64) run_id PK
        varchar(64) source_name
        timestamp_tz started_at
        timestamp_tz completed_at
        integer rows_fetched
        integer rows_ingested
        integer rows_quarantined
        varchar(32) status
        text error_message
    }

    SENSOR_HEALTH {
        bigserial id PK
        varchar(64) station_id FK
        varchar(32) parameter
        double_precision coverage_ratio
        boolean drift_detected
        boolean flatline_detected
        timestamp_tz evaluation_window_start
        timestamp_tz evaluation_window_end
        timestamp_tz created_at
    }

    ANOMALY_EVENTS {
        bigserial id PK
        varchar(64) station_id FK
        varchar(32) parameter
        double_precision observed_value
        double_precision baseline_median
        double_precision mad_score
        varchar(32) anomaly_type
        timestamp_tz timestamp_utc
        timestamp_tz detected_at
    }

    QUARANTINE_RECORDS {
        bigserial id PK
        varchar(64) run_id FK
        varchar(64) station_id FK
        varchar(64) source_name
        text failure_reason
        varchar(64) error_code
        jsonb raw_payload
        timestamp_tz quarantined_at
    }

```

### How to read this diagram

This ER diagram shows the relational schema declared in `docker/postgres-init/01-init-control-plane.sql` and managed by `src/aq_engine/storage/db.py`, including keys, table columns, and foreign key relationships.

### Important observations

* **Control Plane Focus:** Tables store operational metrics, audits, and health scorecards rather than high-frequency raw sensor telemetry.


* **Foreign Key Integrity:** `station_id` anchors anomalies, sensor health logs, and quarantine entries back to the primary `stations` dimension.


* **JSONB Quarantine Flexibility:** `QUARANTINE_RECORDS` stores the malformed `raw_payload` as `JSONB`, ensuring arbitrary schema deviations can be inspected without causing ingestion crashes.



### Questions to ask yourself

1. What index should be placed on `ANOMALY_EVENTS` to optimize time-range queries per station?
2. Why is `QUARANTINE_RECORDS.raw_payload` stored as `jsonb` instead of discrete columns?
3. How does `INGESTION_RUNS` track partial failures versus total pipeline aborts?
4. What happens to `SENSOR_HEALTH` records if a station is deleted from the `STATIONS` table?
5. Why are hourly environmental facts not stored as a table in this relational schema?

---

## 9. Sequence Diagrams for 5 Core Operations

### Sequence 1: Hourly Ingestion & Validation Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant Airflow as Airflow DAG
    participant Orch as IngestionOrchestrator
    participant Conn as OpenAQConnector
    participant Val as DataQualityValidator
    participant Parquet as ParquetIO
    participant DB as DatabaseManager

    Airflow->>Orch: run(source="openaq", window_hours=1)
    activate Orch
    Orch->>DB: create_ingestion_run()
    DB-->>Orch: run_id

    Orch->>Conn: fetch_measurements(since, until)
    activate Conn
    Conn-->>Orch: raw_records[]
    deactivate Conn

    Orch->>Val: validate(raw_records)
    activate Val
    Val->>Val: Check ranges, types, nulls
    Val->>Val: Compute SHA-256 deduplication hash
    Val-->>Orch: ValidationResult(valid_df, quarantine_df)
    deactivate Val

    alt Has Quarantined Records
        Orch->>DB: insert_quarantine_records(run_id, quarantine_df)
    end

    Orch->>Parquet: append_partitioned(valid_df, path="/processed/hourly_facts")
    activate Parquet
    Parquet-->>Orch: write_success
    deactivate Parquet

    Orch->>DB: update_ingestion_run(run_id, status="SUCCESS", counts)
    Orch-->>Airflow: Pipeline Execution Complete
    deactivate Orch

```

---

### Sequence 2: Statistical Anomaly Detection (MAD)

```mermaid
sequenceDiagram
    autonumber
    participant Scheduler as Scheduler / Worker
    participant Anom as AnomalyDetector
    participant Parquet as ParquetIO
    participant DB as DatabaseManager

    Scheduler->>Anom: evaluate_anomalies(window_hours=24)
    activate Anom
    Anom->>Parquet: read_recent_slice(window_hours=24)
    Parquet-->>Anom: observation_df

    loop For each Station & Parameter
        Anom->>Anom: Calculate Median (x_median)
        Anom->>Anom: Calculate MAD = Median(|x_i - x_median|)
        Anom->>Anom: Calculate Score = |x_i - x_median| / (1.4826 * MAD)
        alt Score > Threshold (e.g., 3.5)
            Anom->>Anom: Flag AnomalyEvent
        end
    end

    Anom->>DB: insert_anomaly_events(anomaly_events[])
    DB-->>Anom: commit_ok
    Anom-->>Scheduler: Anomaly Evaluation Summary
    deactivate Anom

```

---

### Sequence 3: Sensor Health & Reliability Evaluation

```mermaid
sequenceDiagram
    autonumber
    participant CLI as CLI / Scheduler
    participant Health as StationHealthEvaluator
    participant Parquet as ParquetIO
    participant DB as DatabaseManager

    CLI->>Health: evaluate_station_health(window_days=7)
    activate Health
    Health->>Parquet: read_station_slice(window_days=7)
    Parquet-->>Health: time_series_df

    Health->>Health: Calculate Coverage Ratio (actual_count / expected_count)
    Health->>Health: Check Flatline (rolling std_dev == 0 over window)
    Health->>Health: Check Drift (gradual baseline deviation slope)

    Health->>DB: insert_sensor_health_scorecard(health_metrics)
    DB-->>Health: ok
    Health-->>CLI: Return Health Summary
    deactivate Health

```

---

### Sequence 4: Machine Learning Model Training Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant DAG as Model Retrain DAG
    participant Trainer as ModelTrainer
    participant Storage as ParquetIO
    participant Splitter as TimeSeriesSplitter
    participant Feat as FeaturePipeline
    participant Base as BaselineModels
    participant Disk as Artifact Storage

    DAG->>Trainer: train_forecast_model(target="pm25", horizon=24)
    activate Trainer
    Trainer->>Storage: load_dataset(lookback_days=90)
    Storage-->>Trainer: dataset_df

    Trainer->>Feat: transform(dataset_df)
    Feat-->>Trainer: feature_matrix (lags, rolling, weather, cyclical)

    Trainer->>Splitter: generate_purged_splits(feature_matrix)
    Splitter-->>Trainer: (train_indices, val_indices)[]

    Trainer->>Base: evaluate_baselines(rolling_mean, persistence)
    Base-->>Trainer: baseline_metrics (RMSE, MAE)

    Trainer->>Trainer: fit_lightgbm(X_train, y_train, X_val, y_val)
    Trainer->>Trainer: evaluate_model_uplift(model_rmse vs baseline_rmse)

    alt Model Outperforms Baseline
        Trainer->>Disk: save_model_artifact("models/pm25_lgbm.booster")
        Trainer-->>DAG: Retraining Success (Metrics logged)
    else Model Fails Uplift Check
        Trainer-->>DAG: Retraining Rejected (Keep existing artifact)
    end
    deactivate Trainer

```

---

### Sequence 5: API Real-Time Forecast Query

```mermaid
sequenceDiagram
    autonumber
    participant Client as API Client
    participant API as FastAPI Router
    participant Parquet as ParquetIO
    participant Feat as FeaturePipeline
    participant Infer as InferenceEngine

    Client->>API: GET /api/v1/observations/stations/ST_01/forecast?horizon=24
    activate API
    API->>Parquet: get_recent_history(station_id="ST_01", hours=72)
    Parquet-->>API: historical_df

    API->>Parquet: get_weather_forecast(station_id="ST_01", hours=24)
    Parquet-->>API: weather_forecast_df

    API->>Feat: build_inference_features(historical_df, weather_forecast_df)
    Feat-->>API: inference_matrix

    API->>Infer: predict(inference_matrix)
    activate Infer
    Infer->>Infer: load_cached_booster()
    Infer-->>API: predicted_values[]
    deactivate Infer

    API->>API: Format Pydantic ForecastResponse
    API-->>Client: 200 OK (JSON Forecast Array)
    deactivate API

```

### How to read these sequence diagrams

These sequence diagrams follow the step-by-step method calls across objects, showing parameter passes, data transformations, branch conditions (e.g., `alt`), and asynchronous or synchronous completions.

### Important observations

* **Idempotent Ingestion Check (Sequence 1):** Ingestion runs are formally tracked with state identifiers in PostgreSQL before data commits to disk.


* **Baseline Uplift Gate (Sequence 4):** A trained machine learning model is only persisted if it objectively beats naive and persistence baseline models in evaluation.


* **Feature Pipeline Reuse (Sequence 4 & 5):** Feature engineering is centralized in a shared component used during both training and real-time inference.



### Questions to ask yourself

1. In Sequence 1, what happens if the worker process crashes after step 6 but before step 7?
2. In Sequence 2, how is the threshold multiplier ($k=3.5$) configured?
3. In Sequence 3, how does `StationHealthEvaluator` determine expected record count across missing hours?
4. In Sequence 4, what prevents future test fold records from leaking into training feature transformations?
5. In Sequence 5, what fallback response occurs if no model artifact has been trained yet?

---

## 10. Deployment Architecture & CI/CD Pipeline

```mermaid
flowchart TB
    subgraph GitHubRepo["GitHub Repository & CI/CD Workflows"]
        GitPush["git push / PR"]
        
        subgraph Actions[".github/workflows/"]
            CIWorkflow["ci.yml\n(Linting, Formatting, Unit Tests)"]
            ContractWorkflow["data-contract-check.yml\n(Schema Validation)"]
            DockerWorkflow["docker-build.yml\n(Image Build & Test)"]
            PerfWorkflow["performance.yml\n(Benchmark Regressions)"]
        end
        
        GitPush --> CIWorkflow
        GitPush --> ContractWorkflow
        GitPush --> DockerWorkflow
        GitPush --> PerfWorkflow
    end

    subgraph HostEnvironment["Deployment Host / VM"]
        subgraph DockerComposeRuntime["Docker Compose Network (aq_network)"]
            APIService["fastapi-api:8000\n(Dockerfile.api)"]
            DashboardService["streamlit-dashboard:8501\n(Dockerfile.dashboard)"]
            WorkerService["aq-worker\n(Dockerfile.worker)"]
            PostgresService[("postgres:5432\n(Volume: pgdata)")]
        end

        subgraph LocalHostStorage["Host File System Volumes"]
            SharedDataVolume["/var/data/aq_engine/\n├── /raw\n├── /processed\n└── /quarantine"]
            ModelVolume["/var/models/"]
        end
    end

    DockerWorkflow -.->|"Deploys Container Images"| DockerComposeRuntime

    APIService <--> PostgresService
    WorkerService <--> PostgresService
    
    APIService --> SharedDataVolume
    WorkerService --> SharedDataVolume
    
    APIService --> ModelVolume
    WorkerService --> ModelVolume

    DashboardService -->|"HTTP internal"| APIService

```

### How to read this diagram

This diagram illustrates the bridge between the GitHub Actions CI/CD automation and the Docker Compose runtime deployment model defined in `docker-compose.yml`.

### Important observations

* **Multi-Stage CI/CD Guardrails:** Every code change is verified by unit tests, schema contract adherence checks, multi-container Docker image builds, and performance benchmarks before merging.


* **Shared Storage Mounts:** The deployment relies on mapped bind volumes to ensure Parquet files and trained model artifacts persist across container rebuilds and restarts.


* **Isolated Container Network:** All services communicate within a private Docker bridge network (`aq_network`), with only designated ports (8000, 8501, 5432) exposed as needed.



### Unknowns & Non-Determined Elements

* **Cloud Orchestrator:** The repository provides Docker Compose and Dockerfiles; it does **not** include Kubernetes manifests, Helm charts, AWS ECS task definitions, or Terraform infrastructure-as-code files. Cloud infrastructure topology is explicitly marked as **unknown / not implemented in this repository**.



### Questions to ask yourself

1. How do the GitHub Actions workflows run integration tests that require PostgreSQL?
2. What volume permissions must be configured on the host machine to allow container workers to write to `/var/data/aq_engine/`?
3. How can the Docker Compose configuration be migrated to high-availability Kubernetes deployments?
4. How are database migrations executed when a new version of the application is deployed?
5. What monitoring mechanism watches the health of the Airflow scheduler container?