 Architecture Summary: Air Quality Intelligence Platform                                                              
                                                                                                                      
 Overview                                                                                                             
                                                                                                                      
 A local-first, open-source data engineering and analytics system for real-time air quality monitoring, anomaly       
 detection, and near-term PM2.5 forecasting. It ingests data from OpenAQ (air quality) and Open-Meteo (weather), runs 
 it through a multi-stage quality pipeline, computes baselines, detects anomalies and pollution events, trains        
 CPU-friendly ML models, and serves everything via a FastAPI REST API and a Streamlit dashboard.                      
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Three-Plane Architecture                                                                                             
                                                                                                                      
 The system is organized into three logical planes, as defined in the README and reflected in the code:               
                                                                                                                      
 ### 1. Data Plane                                                                                                    
                                                                                                                      
 Ingestion → Raw Storage → Quality Validation → Clean Storage → Transformation                                        
                                                                                                                      
 - Connectors (src/aq_engine/connectors/): Abstract BaseConnector with two implementations — OpenAQConnector (air     
   quality) and OpenMeteoConnector (weather). The base class provides HTTP session management with retry +            
   exponential backoff, token-bucket rate limiting, response caching, and structured logging. Each connector          
   implements fetch(), parse(), validate_source_response(), write_raw(), and record_run().                            
 - Ingestion Orchestrator (src/aq_engine/ingestion/orchestrator.py): Coordinates the end-to-end workflow for each     
   source. Implements idempotency via measurement keys (generated from source+station+sensor+pollutant+timestamp),    
   watermark-based incremental ingestion (reads last successful watermark from PostgreSQL, queries for new data since 
   then), and a ingest_source_backfill() method for historical date-range ingestion. Failed runs record metadata but  
   do not advance the watermark.                                                                                      
 - Storage (src/aq_engine/storage/): Two backends — ParquetWriter for immutable file-based storage (partitioned by    
   date, source-specific writers for air quality and weather), and Database (PostgreSQL via SQLAlchemy) for the       
   control plane with repositories for ingestion runs, locations, and stations.                                       
 - Quality (src/aq_engine/quality/): A QualityValidator classifies each record as VALID, SUSPICIOUS, or INVALID using 
   5 air-quality rules (structural, semantic, temporal, outlier, stale/flatline) and 3 weather rules (structural,     
   semantic, temporal). Deduplication uses SHA-256 hashing of raw payloads. Quarantined records go to a separate      
   store. Late-arrival handling detects records older than a configurable threshold.                                  
                                                                                                                      
 ### 2. Intelligence Plane                                                                                            
                                                                                                                      
 Analytics → Anomaly Detection → Event Detection → ML Forecasting                                                     
                                                                                                                      
 - Analytics (src/aq_engine/analytics/):                                                                              
     - aggregation.py (LocationAggregator): Computes hourly facts per location — counts, mean, median, min, max,      
       stddev, coverage percentage.                                                                                   
     - baselines.py: Computes historical baselines by location × pollutant × month × hour-of-day, including median,   
       MAD (Median Absolute Deviation), and percentiles (p50, p75, p90, p95, p99) over configurable baseline windows  
       (default 365 days).                                                                                            
     - anomaly.py (AnomalyDetector): Uses MAD-based robust Z-score (robust_z = (x - median) / (1.4826 × MAD)) with a  
       5-tier severity classification (NORMAL → ELEVATED → HIGH → SEVERE → EXTREME). Includes fallback logic: if MAD  
       is zero (constant history), falls back to a percentile-rank heuristic; if the primary baseline is missing,     
       falls back to city-wide or 7-day recent baselines.                                                             
     - events.py (EventDetector): Groups consecutive anomalous readings into persistent pollution events using        
       configurable thresholds (minimum anomalies, minimum window hours, merge gaps).                                 
     - station_health.py: Computes station health scores based on coverage, data quality, and uptime.                 
                                                                                                                      
 - ML (src/aq_engine/ml/):                                                                                            
     - features.py: Generates 46 features including lags, rolling statistics (1h/3h/6h windows), weather              
       correlations, time-based features (hour, day-of-week, month), and baseline deviations.                         
     - split.py: Time-series-aware split (no random shuffling) to prevent data leakage, with configurable test        
       fraction.                                                                                                      
     - baselines.py: Naive (persistence) and seasonal naive baselines for comparison.                                 
     - training.py: Trains multiple candidate models (Random Forest, Gradient Boosting, Extra Trees, Hist Gradient    
       Boosting) with CPU optimization. Selection uses a promotion threshold (default 5% improvement over baseline).  
     - evaluation.py: Computes MAE, RMSE, MAPE, and performs model comparison.                                        
     - inference.py: Generates multi-horizon predictions (1h, 3h, 6h) with prediction intervals.                      
     - registry.py: Model registry tracking versions, status (training/ready/active/deprecated), and performance      
       metrics.                                                                                                       
                                                                                                                      
 ### 3. Control Plane                                                                                                 
                                                                                                                      
 PostgreSQL metadata, lineage, model registry, watermark management                                                   
                                                                                                                      
 A single Postgres instance holds all metadata (initialized via docker/postgres-init/01-init-control-plane.sql), with 
 12 tables:                                                                                                           
                                                                                                                      
 - source — data source definitions (OpenAQ, Open-Meteo)                                                              
 - location — geographic locations (city, country, lat/lon, timezone)                                                 
 - station — physical monitoring stations, linked to sources and locations                                            
 - sensor — individual sensors, linked to stations and pollutants                                                     
 - ingestion_run — audit log of every ingestion run (UUID, status, record counts, watermarks, errors)                 
 - quality_run — audit log of quality validation runs                                                                 
 - model + model_version — ML model registry with metrics and status                                                  
 - prediction — generated forecasts with actuals for backtesting                                                      
 - 4 views: v_active_stations, v_recent_ingestion_runs, v_active_models                                               
                                                                                                                      
 All tables have created_at/updated_at timestamps with auto-updating triggers. Composite indexes support common query 
 patterns.                                                                                                            
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Data Flow (End-to-End)                                                                                               
                                                                                                                      
 ```                                                                                                                  
   1. Ingestion (via CLI or Airflow DAG)                                                                              
      → OpenAQ/Open-Meteo API                                                                                         
      → BaseConnector.fetch() with retry/rate-limit                                                                   
      → parse() into canonical records                                                                                
      → QualityValidator.validate_batch() → VALID/SUSPICIOUS/INVALID                                                  
      → Deduplication via measurement keys                                                                            
      → ParquetWriter.write_*_raw() to /data/raw/{source}/{date}/                                                     
      → IngestionRunRepository.record_run() to PostgreSQL (watermark advanced on success)                             
                                                                                                                      
   2. Transformation (dbt, run via Airflow or Docker)                                                                 
      → dbt staging models (int_* ) clean & dedupe                                                                    
      → dbt marts (hourly_air_quality_facts, hourly_weather_facts) aggregate to hourly                                
      → dbt joins with dim_ tables for location mapping & baseline comparisons                                        
                                                                                                                      
   3. Analytics (run via CLI or Airflow)                                                                              
      → LocationAggregator → hourly facts (or via dbt)                                                                
      → Baselines computed per location × pollutant × month × hour                                                    
      → AnomalyDetector.detect_batch() → robust Z-scores + severity                                                   
      → EventDetector groups anomalies into pollution events                                                          
                                                                                                                      
   4. ML (run via Airflow aq_model_retrain_dag)                                                                       
      → Features generated (46 features)                                                                              
      → Time-series split                                                                                             
      → 4 candidate models trained (CPU-optimized)                                                                    
      → Best model promoted to active if >5% improvement over baseline                                                
      → Inference generates 1h/3h/6h forecasts                                                                        
                                                                                                                      
   5. Serving                                                                                                         
      → FastAPI (port 8000): REST API with /api/locations, /api/locations/{id}/current,                               
        /forecast, /events, /baseline, /system/health, /system/quality                                                
      → Streamlit Dashboard (port 8501): Interactive visualizations                                                   
 ```                                                                                                                  
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Orchestration Layer (Airflow)                                                                                        
                                                                                                                      
 Three DAGs in dags/:                                                                                                 
 - aq_hourly_ingest_dag.py — Hourly incremental ingestion from both sources                                           
 - aq_daily_backfill_dag.py — Daily backfill over a configurable date range                                           
 - aq_model_retrain_dag.py — Daily model retraining and registry promotion                                            
                                                                                                                      
 Airflow runs in Docker Compose using LocalExecutor backed by PostgreSQL. The scheduler and webserver are separate    
 services.                                                                                                            
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 CLI Layer                                                                                                            
                                                                                                                      
 A Typer-based CLI (src/aq_engine/cli.py) with commands:                                                              
 - ingest — fetch from a single source for a date range                                                               
 - validate — run quality validation on stored raw data                                                               
 - aggregate — compute hourly aggregates                                                                              
 - detect-anomalies — run anomaly detection for a date                                                                
 - detect-events — run pollution event detection for a date                                                           
 - train — train ML models for a target (pm25_1h / 3h / 6h)                                                           
 - predict — generate forecasts for a horizon                                                                         
 - backfill — backfill historical data across a date range                                                            
 - health — check database and storage connectivity                                                                   
 - api — start the FastAPI server                                                                                     
 - dashboard — launch info for the Streamlit dashboard                                                                
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Configuration                                                                                                        
                                                                                                                      
 - YAML config (configs/default.yaml, configs/base.yaml, configs/sources/*.yaml) defines all connection strings, API  
   keys, timeouts, quality thresholds, ML parameters, and analytics parameters.                                       
 - Pydantic models (src/aq_engine/config.py) validate configuration with nested models (DatabaseConfig, DataConfig,   
   APIConfig, ConnectorsConfig, AirflowConfig, MLConfig, AnalyticsConfig). Environment variables override YAML values 
   (e.g., DATABASE_URL, API_PORT, OPENAQ_API_KEY).                                                                    
 - Logging config (configs/logging.yaml) supports JSON and standard formatters.                                       
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Services (Docker Compose)                                                                                            
                                                                                                                      
 ┌───────────────────┬────────────────────────┬──────┬───────────────────────────────┐                                
 │ Service           │ Image                  │ Port │ Purpose                       │                                
 ├───────────────────┼────────────────────────┼──────┼───────────────────────────────┤                                
 │ postgres          │ postgres:15.4-alpine   │ 5432 │ Control plane metadata        │                                
 ├───────────────────┼────────────────────────┼──────┼───────────────────────────────┤                                
 │ airflow-init      │ Custom worker image    │ —    │ One-time DB init + admin user │                                
 ├───────────────────┼────────────────────────┼──────┼───────────────────────────────┤                                
 │ airflow-scheduler │ Custom worker image    │ —    │ DAG scheduling                │                                
 ├───────────────────┼────────────────────────┼──────┼───────────────────────────────┤                                
 │ airflow-webserver │ Custom worker image    │ 8080 │ Airflow UI                    │                                
 ├───────────────────┼────────────────────────┼──────┼───────────────────────────────┤                                
 │ api               │ Custom API image       │ 8000 │ FastAPI REST server           │                                
 ├───────────────────┼────────────────────────┼──────┼───────────────────────────────┤                                
 │ dashboard         │ Custom dashboard image │ 8501 │ Streamlit UI                  │                                
 └───────────────────┴────────────────────────┴──────┴───────────────────────────────┘                                
                                                                                                                      
 All services share a single aq-net bridge network. PostgreSQL uses a named volume (aq-postgres-data). Source code    
 and configs are mounted as read-only volumes for the API and dashboard services.                                     
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Data Storage Layout                                                                                                  
                                                                                                                      
 On disk (/data):                                                                                                     
                                                                                                                      
 ```                                                                                                                  
   data/                                                                                                              
   ├── raw/                    # Immutable raw observations (partitioned by date)                                     
   │   ├── openaq/2026-08-15/                                                                                         
   │   └── open_meteo/2026-08-15/                                                                                     
   ├── clean/                  # Validated/cleaned data                                                               
   ├── quarantine/             # Rejected records                                                                     
   ├── mart/                   # Aggregated analytical tables (hourly/daily)                                          
   └── models/                 # Serialized ML model artifacts                                                        
 ```                                                                                                                  
                                                                                                                      
 Parquet is the primary data format (immutable, column-oriented, partitioned by date). PostgreSQL handles only        
 metadata/control plane data.                                                                                         
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Technology Stack                                                                                                     
                                                                                                                      
 ┌──────────────────┬──────────────────────────────────────────────────────────────────────────────────┐              
 │ Layer            │ Technology                                                                       │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Language         │ Python 3.12+                                                                     │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Data Formats     │ Parquet (primary), JSON (API, configs)                                           │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Storage Engine   │ DuckDB (SQL over Parquet), Polars (transforms)                                   │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Database         │ PostgreSQL 15 (control plane)                                                    │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Transform Tool   │ dbt Core                                                                         │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Orchestration    │ Apache Airflow (LocalExecutor)                                                   │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ ML               │ scikit-learn (CPU-friendly: RandomForest, GradientBoosting, ExtraTrees, HistGBM) │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ API              │ FastAPI (Pydantic v2 validation, CORS, structured logging middleware)            │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Dashboard        │ Streamlit                                                                        │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ CLI              │ Typer (Rich console output)                                                      │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Configuration    │ Pydantic + YAML                                                                  │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Containerization │ Docker Compose                                                                   │              
 ├──────────────────┼──────────────────────────────────────────────────────────────────────────────────┤              
 │ Testing          │ pytest (unit, integration, performance)                                          │              
 └──────────────────┴──────────────────────────────────────────────────────────────────────────────────┘              
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Testing Strategy                                                                                                     
                                                                                                                      
 - Unit tests (tests/unit/) — 20+ test files covering connectors, quality validation, anomaly detection, baselines,   
   aggregation, ml training/inference, API endpoints, CLI, DAG structure                                              
 - Integration tests (tests/integration/) — End-to-end scenarios, idempotent ingestion, deduplication, hourly facts,  
   backfill DAG, failure recovery                                                                                     
 - Performance tests (tests/performance/) — API response time, ingestion throughput, ML training/inference latency    
                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                     
                                                                                                                      
 Key Design Decisions (from ADRs)                                                                                     
                                                                                                                      
 - MAD over standard deviation for anomaly detection — robust to historical outliers                                  
 - Dual storage (PostgreSQL for metadata + Parquet for data) — separates transactional concerns from analytical       
   storage                                                                                                            
 - Token bucket rate limiting in connectors — thread-safe, configurable per source                                    
 - Time-series aware ML splits — no random shuffling to prevent temporal leakage                                      
 - 5% relative improvement threshold for model promotion — prevents churn from marginal gains    