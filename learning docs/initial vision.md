AIR QUALITY INTELLIGENCE PLATFORM
Technical Product & Engineering Blueprint
Team-ready engineering baseline • Local-first • Open-source/free-tier stack

Attribute	Specification
Document status	Engineering Baseline
Target geography	Kolkata initially; multi-city architecture
Hardware target	AMD Ryzen 3 • 16 GB RAM • No GPU
Cost constraint	Open-source software + free/public data sources
Primary target	PM2.5 concentration
Forecast horizons	1h, 3h, 6h initially; 12h/24h later
Primary users	Engineering, analytics, data-science, operations

 
Document Contents
1. Product Definition
2. Scope and Boundaries
3. Non-Functional Requirements
4. Technology Stack
5. External Data Sources
6. System Architecture
7. Storage Architecture
8. PostgreSQL Data Model
9. Data Contracts
10. Ingestion Engineering
11. Data Quality
12. Analytics Layer
13. Anomaly and Event Detection
14. Forecasting / Data Science
15. API and Dashboard
16. Orchestration
17. Observability and Lineage
18. Testing and Acceptance Criteria
19. Performance
20. Development Plan
21. Definition of Done
22. Repository and Documentation Deliverables
1. Product Definition
The Air Quality Intelligence Platform is a local-first data engineering and analytics system that continuously collects air-quality and weather observations, validates and stores them, produces hourly analytical datasets, identifies abnormal pollution behaviour, detects persistent pollution events, forecasts near-term PM2.5, evaluates model performance, and exposes the results through an API and dashboard.
1.1 Problem Statement
•	Current-value dashboards do not reliably distinguish normal seasonal/hourly variation from unusual pollution.
•	Raw sensor data can contain duplicates, missing observations, stale values, flatlines and malformed records.
•	Forecasts without strict time-series validation can suffer from future-data leakage.
•	Operational failures are often invisible unless ingestion, quality, model and freshness states are tracked together.
1.2 Product Questions
•	Is current pollution normal for this location and time?
•	Is the increase persistent enough to qualify as an event?
•	Which stations are producing unreliable measurements?
•	What weather conditions accompany elevated PM2.5?
•	What PM2.5 level is expected 1–6 hours ahead?
•	How accurate are the forecasts and are they degrading?
2. Scope and Boundaries
2.1 In Scope
•	Air-quality ingestion, normalization, deduplication and late-arrival handling.
•	Weather ingestion and alignment to air-quality observations.
•	Raw immutable storage in Parquet.
•	PostgreSQL metadata/control plane.
•	Hourly/daily analytical marts.
•	Historical baselines, percentiles and anomaly scores.
•	Pollution-event detection and event merging.
•	Station-health scoring.
•	CPU-friendly PM2.5 forecasting.
•	REST API, dashboard, pipeline monitoring and model monitoring.
2.2 Explicitly Out of Scope for V1
•	Deep learning, GPUs, LLMs, computer vision or satellite-image processing.
•	Spark, Kafka, Kubernetes or cloud infrastructure.
•	Paid data sources and paid infrastructure.
•	Mobile application and user authentication.
•	Medical/health diagnosis or individualized health advice.
•	Causal claims about pollution sources without a causal methodology.
3. Non-Functional Requirements
Requirement	Target
Hardware	Ryzen 3 / 16 GB RAM / no GPU
PostgreSQL memory target	≤ 1.5 GB
Airflow target	≤ 2.5 GB
API + dashboard	≤ 1.0 GB
Pipeline process	≤ 3.0 GB
Analytical workload	DuckDB/Parquet; avoid loading full history into Python
Reproducibility	Docker Compose + pinned dependencies
Idempotency	Repeated ingestion/backfill produces same canonical result
Auditability	Every run/artifact traceable to source and version

4. Technology Stack
Concern	Technology	Purpose
Language	Python 3.12+	Connectors, quality, features, ML, API
OLTP/control plane	PostgreSQL	Metadata, state, registry
Analytics engine	DuckDB	SQL analytics over Parquet
Columnar storage	Parquet	Raw/clean/mart persistence
Data processing	Polars	Memory-efficient transformations
Transformation/testing	dbt Core	SQL models and tests
Orchestration	Apache Airflow	DAGs, retries, backfills
ML	scikit-learn	CPU-friendly forecasting
Optional ML	XGBoost	Gradient boosting benchmark
API	FastAPI	Serving
Dashboard	Streamlit	Analytical UI
Testing	pytest	Unit/integration tests
Packaging	Docker Compose	Reproducible local deployment

5. External Data Sources
5.1 Air Quality — OpenAQ
Use OpenAQ as the primary public air-quality source. Canonical fields include station/sensor identity, pollutant, value, unit and observation timestamp.
Documentation: https://docs.openaq.org/
5.2 Weather — Open-Meteo
Use Open-Meteo for temperature, relative humidity, wind speed/direction, pressure, precipitation and cloud cover.
Documentation: https://open-meteo.com/en/docs/
6. System Architecture
                    EXTERNAL SOURCES
                   /                \
                  /                  \
             OpenAQ                Open-Meteo
                |                     |
                +----------+----------+
                           |
                           v
                  INGESTION SERVICES
                           |
                           v
                    RAW DATA LAYER
                       Parquet
                           |
                           v
                    DATA QUALITY
                     /         \
                  valid      rejected
                    |           |
                    v           v
                CLEAN LAYER  QUARANTINE
                    |
                    v
             TRANSFORMATION LAYER
                Polars / dbt
                    |
             +------+-------+
             |              |
             v              v
       ANALYTICAL MARTS   FEATURES
             |              |
             |              v
             |          ML TRAINING
             |              |
             |              v
             |        MODEL ARTIFACTS
             |              |
             +------+-------+
                    |
                    v
                PREDICTIONS
                 /       \
                v         v
             FastAPI  Streamlit

 PostgreSQL = metadata/control plane

6.1 Architectural Principles
•	Raw data is immutable; cleaning happens downstream.
•	PostgreSQL is the control/metadata plane, not the bulk analytical store.
•	Parquet is the durable analytical storage layer.
•	DuckDB is used for analytical SQL over Parquet.
•	Every transformation must be reproducible from versioned code and source data.
•	Model promotion is conservative: failed or inferior candidates never replace the production model.
7. Storage Architecture
data/
├── raw/
│   ├── openaq/year=YYYY/month=MM/day=DD/
│   └── weather/year=YYYY/month=MM/day=DD/
├── clean/
│   ├── air_quality/
│   └── weather/
├── marts/
│   ├── hourly_air_quality/
│   ├── daily_air_quality/
│   ├── weather_hourly/
│   ├── anomaly/
│   ├── pollution_events/
│   ├── station_health/
│   └── ml_features/
└── quarantine/
    ├── air_quality/
    └── weather/

Partition raw/clean/mart Parquet by date (year/month/day). Avoid high-cardinality station partitions that create tiny files.
8. PostgreSQL Data Model
PostgreSQL stores source configuration, location/station/sensor metadata, ingestion state, quality runs, model registry and prediction metadata.
source
source_id BIGSERIAL PRIMARY KEY
source_name TEXT UNIQUE NOT NULL
source_type TEXT NOT NULL
base_url TEXT
active BOOLEAN DEFAULT TRUE
created_at TIMESTAMPTZ NOT NULL
location
location_id BIGSERIAL PRIMARY KEY
location_code TEXT UNIQUE NOT NULL
name TEXT NOT NULL
city TEXT NOT NULL
country TEXT NOT NULL
latitude DOUBLE PRECISION NOT NULL
longitude DOUBLE PRECISION NOT NULL
timezone TEXT NOT NULL
elevation_m DOUBLE PRECISION
station
station_id BIGSERIAL PRIMARY KEY
source_id BIGINT REFERENCES source(source_id)
source_station_id TEXT NOT NULL
location_id BIGINT REFERENCES location(location_id)
station_name TEXT
station_type TEXT
latitude DOUBLE PRECISION
longitude DOUBLE PRECISION
first_seen_at TIMESTAMPTZ
last_seen_at TIMESTAMPTZ
is_active BOOLEAN DEFAULT TRUE
UNIQUE(source_id, source_station_id)
sensor
sensor_id BIGSERIAL PRIMARY KEY
station_id BIGINT REFERENCES station(station_id)
source_sensor_id TEXT NOT NULL
pollutant_code TEXT NOT NULL
unit TEXT NOT NULL
first_seen_at TIMESTAMPTZ
last_seen_at TIMESTAMPTZ
UNIQUE(station_id, source_sensor_id, pollutant_code)
ingestion_run
run_id UUID PRIMARY KEY
source_id BIGINT REFERENCES source(source_id)
started_at TIMESTAMPTZ NOT NULL
finished_at TIMESTAMPTZ
status TEXT NOT NULL
requested_start TIMESTAMPTZ
requested_end TIMESTAMPTZ
records_received BIGINT DEFAULT 0
records_written BIGINT DEFAULT 0
records_rejected BIGINT DEFAULT 0
error_message TEXT
quality_run
quality_run_id UUID PRIMARY KEY
started_at TIMESTAMPTZ NOT NULL
finished_at TIMESTAMPTZ
input_records BIGINT
valid_records BIGINT
suspicious_records BIGINT
invalid_records BIGINT
status TEXT NOT NULL
model
model_id BIGSERIAL PRIMARY KEY
model_name TEXT NOT NULL
model_type TEXT NOT NULL
target TEXT NOT NULL
created_at TIMESTAMPTZ NOT NULL
model_version
model_version_id BIGSERIAL PRIMARY KEY
model_id BIGINT REFERENCES model(model_id)
version TEXT NOT NULL
feature_version TEXT NOT NULL
training_start TIMESTAMPTZ NOT NULL
training_end TIMESTAMPTZ NOT NULL
mae DOUBLE PRECISION
rmse DOUBLE PRECISION
artifact_path TEXT NOT NULL
status TEXT NOT NULL
created_at TIMESTAMPTZ NOT NULL
UNIQUE(model_id, version)
prediction
prediction_id BIGSERIAL PRIMARY KEY
model_version_id BIGINT REFERENCES model_version(model_version_id)
location_id BIGINT REFERENCES location(location_id)
generated_at TIMESTAMPTZ NOT NULL
target_time TIMESTAMPTZ NOT NULL
horizon_minutes INTEGER NOT NULL
predicted_pm25 DOUBLE PRECISION
lower_bound DOUBLE PRECISION
upper_bound DOUBLE PRECISION
actual_pm25 DOUBLE PRECISION
absolute_error DOUBLE PRECISION
9. Data Contracts
9.1 Canonical Air-Quality Record
source
station_id
sensor_id
pollutant
value
unit
observed_at
ingested_at
raw_payload_hash
measurement_key
measurement_key = SHA256(source + station + sensor + pollutant + observed_at). It is the idempotency key.
9.2 Canonical Weather Record
source
location_id
observed_at
temperature_c
humidity_pct
wind_speed_kmh
wind_direction_deg
pressure_hpa
precipitation_mm
cloud_cover_pct
ingested_at
raw_payload_hash
9.3 Hourly Fact Grain
station_id
location_id
hour_start
pollutant
mean_value
median_value
min_value
max_value
stddev
observation_count
expected_observation_count
coverage_pct
quality_score
10. Ingestion Engineering
10.1 Connector Interface
fetch()
parse()
validate_source_response()
write_raw()
record_run()
10.2 Failure Policy
Condition	Behaviour
HTTP 2xx	Process
HTTP 429	Exponential backoff + retry
HTTP 5xx	Retry
Timeout	Retry
HTTP 4xx	Fail unless explicitly transient
Malformed payload	Quarantine and alert

Default retry count: 3. Suggested delays: 2s, 4s, 8s plus jitter.
10.3 Watermark
Store last successful event time and ingestion time per source. Never advance the watermark after a failed run.
10.4 Late Data
Use a 6-hour lookback for normal late arrivals. Data older than 6 hours is treated as historical/backfill. Recompute affected hourly partitions.
11. Data Quality
Layer	Rules
Structural	Required fields, types, valid timestamp
Semantic	Non-negative pollutant values; humidity 0–100; wind direction 0–360
Temporal	Reject excessively future-dated observations
Referential	Known station/sensor/location
Duplicate	Unique measurement key
Stale/flatline	Repeated identical values flagged suspicious
Outlier	Extreme spikes flagged suspicious; not automatically deleted

11.1 Quality Classes
•	VALID — passes hard validation and no major quality warning.
•	SUSPICIOUS — retained but excluded from sensitive downstream calculations when policy requires.
•	INVALID — quarantined and excluded from canonical analytical datasets.
12. Analytics Layer
12.1 Historical Baseline
For each location/pollutant/month/hour, calculate median, MAD, p50, p75, p90, p95 and p99. Require at least 60 observations; use documented fallbacks when history is insufficient.
12.2 Location Aggregation
For multiple stations, expose station count, median, mean, p25, p75 and max. Prefer the median as the robust location statistic where appropriate.
12.3 Coverage
If a pollutant normally arrives every 5 minutes, expected observations per hour are 12. coverage_pct = received / expected × 100. Always expose coverage with aggregates.
13. Anomaly and Pollution-Event Detection
13.1 Robust Anomaly Score
robust_z = (x - historical_median) / (1.4826 × MAD)
If MAD is zero, use percentile rank or a documented fallback rather than dividing by zero.
Severity	Operational threshold
NORMAL	< 2
ELEVATED	≥ 2
HIGH	≥ 3
SEVERE	≥ 4
EXTREME	≥ 5

Thresholds are configurable operational thresholds, not medical/health standards.
13.2 Pollution Event
Create an event when anomaly severity is HIGH or above for at least 3 consecutive hours, or at least 3 anomalous hours in a 4-hour window. Merge same-location/same-pollutant events separated by ≤1 hour.
event_id
location_id
pollutant
start_time
end_time
duration
peak_value
mean_value
peak_anomaly_score
severity
14. Forecasting / Data Science
14.1 Targets
•	target_pm25_1h
•	target_pm25_3h
•	target_pm25_6h
14.2 Features
PM2.5 lags: 1, 2, 3, 6, 12, 24 hours
Rolling PM2.5: mean 3h, 6h, 12h, 24h; std 6h; max 24h
Weather: temperature, humidity, wind speed/direction, pressure, rain, cloud cover
Weather lags/rollups
Calendar: hour, weekday, month, day-of-year, weekend
Represent wind direction using sin/cos transformations rather than raw degrees.
14.3 Baselines
•	Current-value naive forecast
•	Yesterday/same-hour forecast
•	Rolling-mean forecast
14.4 Candidate Models
•	Linear Regression
•	Random Forest
•	HistGradientBoosting
•	XGBoost (optional benchmark)
14.5 Validation
Use chronological splits or walk-forward validation. Never use random train/test splitting for the forecasting target.
Example:
2023 -> training
2024 -> validation
2025 -> final test
14.6 Model Promotion
Promote a candidate only if it beats the current model by a configured minimum, e.g. ≥5% MAE improvement. Otherwise retain the current model.
14.7 Prediction Intervals
V1: empirical residual-based intervals. Later: conformal prediction.
15. API and Dashboard
15.1 API Endpoints
Endpoint	Purpose
GET /health	Service health/version
GET /locations	Supported locations
GET /locations/{id}/current	Latest observations + freshness + quality
GET /locations/{id}/history	Historical data by range/pollutant/grain
GET /locations/{id}/forecast	Forecast by horizon
GET /locations/{id}/events	Pollution events
GET /stations/{id}/health	Station health metrics
GET /system/quality	Pipeline and data-quality status

15.2 Dashboard Pages
•	Overview — current PM2.5/PM10/NO2, active stations, anomalies, events, 24h trends.
•	Location — current value, baseline, percentile, anomaly score, weather and forecast.
•	Pollution Event — event duration, peak, baseline, anomaly score and weather timeline.
•	Platform Health — ingestion freshness, rejected records, station health, model version/MAE and drift.
16. Orchestration
START
  ├── ingest_openaq
  └── ingest_weather
          |
          v
     validate_raw
          |
          v
     deduplicate
          |
          v
     normalize_units
          |
          v
     hourly_aggregate
       /           \
      v             v
baselines      station_health
      |
      v
anomaly_detection
      |
      v
event_detection
      |
      v
feature_generation
      |
      v
prediction
      |
      v
evaluate_predictions
      |
      v
publish_marts
      |
     END
16.1 Failure Semantics
•	Transient source failure: retry with backoff.
•	Validation failure: quarantine; do not blindly retry.
•	ML failure: keep previous production model active.
•	Backfill: partition-aware, idempotent and auditable.
17. Observability and Lineage
17.1 Run Metadata
run_id
start_time
end_time
status
records_in
records_out
records_rejected
duration
error
17.2 Lineage
Every prediction should be traceable through model version → feature version → hourly dataset → clean records → raw records. Carry ingestion_run_id and transformation/version metadata through major artifacts.
17.3 Station Health
Daily metrics: availability, missing rate, duplicate rate, stale rate, flatline rate and outlier rate. Convert these into a 0–100 health score with documented penalties and clamping.
18. Testing and Acceptance Criteria
Area	Tests
Connectors	Pagination, retry, timeout, malformed response
Parsing	Valid/invalid payloads
Deduplication	Duplicate observations collapse to one
Time	Timezone and late-arrival handling
Units	Canonical conversion
Quality	Negative/null/outlier/flatline cases
Aggregation	Hourly statistics and coverage
Anomaly	Threshold and fallback behaviour
Events	Persistence and merging
Features	No future leakage
ML	Model load/predict and metrics
API	Schema and status-code contract
Pipeline	Failure/retry/resume
Backfill	Idempotency

18.1 Critical Acceptance Tests
1.	Run the same ingestion twice: canonical row count must not double.
2.	Late observation updates the affected hourly aggregate.
3.	Backfilling the same date twice produces the same analytical result.
4.	Flatline sensor is flagged but does not automatically create a pollution event.
5.	A feature-validation test rejects a deliberately future-leaked feature.
6.	A candidate model that does not meet promotion criteria cannot replace production.
19. Performance and Resource Targets
Workload	Engineering target
Incremental hourly ingestion	< 2 minutes for normal workload
Hourly transformation	< 5 minutes
Feature generation	< 5 minutes
Prediction	< 30 seconds

These are benchmark targets for the stated hardware, not contractual guarantees. Measure and revise after representative data volume is available.
20. Development Plan
Milestone	Deliverables
M0 Foundation	Repo, Python environment, Docker Compose, PostgreSQL, config, logging
M1 Ingestion	OpenAQ/Open-Meteo connectors, raw Parquet, run metadata, idempotency
M2 Quality	Validation, quarantine, deduplication, quality reports
M3 Analytics	Hourly facts, historical baselines, station health
M4 Intelligence	Anomaly and pollution-event detection
M5 ML	Baselines, ML models, time-series evaluation, registry, predictions
M6 Serving	FastAPI + Streamlit
M7 Orchestration	Airflow DAG, retries, backfills, monitoring
M8 Hardening	Tests, documentation, performance and failure testing, ADRs

21. Definition of Done
The platform is complete only when the end-to-end operational scenario succeeds:
7.	New source data arrives.
8.	Pipeline ingests it.
9.	Duplicates are removed.
10.	Invalid records are quarantined.
11.	Late records are incorporated.
12.	Affected hourly aggregates are recomputed.
13.	Station health is recalculated.
14.	Historical baselines are updated.
15.	Anomalies and pollution events are updated.
16.	Features are generated without future leakage.
17.	Production model generates forecasts.
18.	Previous predictions are evaluated.
19.	Model performance is recorded.
20.	Dashboard exposes the updated state.
21.	Upstream failure does not destroy the last valid state.
22.	The entire run is traceable by run IDs and versions.
22. Repository and Documentation Deliverables
repository/
├── src/
├── dags/
├── dbt/
├── sql/
├── tests/
├── configs/
├── models/
├── data/
├── docker/
└── docs/
    ├── 01-product-requirements.md
    ├── 02-system-architecture.md
    ├── 03-data-architecture.md
    ├── 04-data-contracts.md
    ├── 05-database-design.md
    ├── 06-data-quality.md
    ├── 07-pipeline-design.md
    ├── 08-analytics-specification.md
    ├── 09-ml-specification.md
    ├── 10-api-specification.md
    ├── 11-dashboard-specification.md
    ├── 12-testing-strategy.md
    ├── 13-observability.md
    ├── 14-security.md
    ├── 15-performance.md
    ├── 16-disaster-recovery.md
    ├── 17-runbook.md
    └── 18-architecture-decisions/

23. Engineering Decision Summary
The platform is intentionally divided into three planes: the Data Plane reliably acquires and stores data; the Intelligence Plane turns data into analytics, anomalies, events and forecasts; and the Control Plane tracks metadata, pipeline state, lineage, model versions and system health. This separation keeps the system realistic for a mid-tier data engineer while still demonstrating DBMS, data engineering, analytics and data-science depth.
Appendix A — Core CLI Contract
aq ingest --source openaq
aq ingest --source weather
aq validate --date 2026-08-15
aq aggregate --date 2026-08-15
aq detect-anomalies --date 2026-08-15
aq detect-events --date 2026-08-15
aq train --target pm25_1h
aq predict --horizon 1h
aq backfill --source openaq --start 2026-01-01 --end 2026-01-07
aq health

Appendix B — Implementation Rule
Do not start by building the dashboard. Build the canonical data model and ingestion/quality path first. A visually impressive dashboard over unreliable measurements is not a successful data-engineering system.
