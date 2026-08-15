# Air Quality Intelligence Platform: System Architecture

## Overview

The Air Quality Intelligence Platform is a production-grade system for monitoring PM2.5 concentrations in Kolkata with local-first data engineering, advanced anomaly detection, and ML-powered forecasting.

**Core Mission:** Provide real-time air quality insights with predictive intelligence for informed decision-making.

**Key Characteristics:**
- **Local-first data engineering:** Watermark-based incremental ingestion
- **Immutable storage:** Parquet files (date-partitioned) + PostgreSQL control plane
- **Robust anomaly detection:** Median Absolute Deviation (MAD) with percentile fallback
- **ML-driven forecasting:** Multi-horizon predictions with empirical confidence intervals
- **Comprehensive testing:** 220+ tests (unit, integration, performance)
- **Production orchestration:** Hourly ingestion, daily backfill, weekly retraining DAGs

## Three-Plane Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      API PLANE                              │
│  (FastAPI, Request/Response, CORS, Rate Limiting)           │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │ /locations   │ /current     │ /forecast    │  ...        │
│  └──────────────┴──────────────┴──────────────┘             │
└─────────────────────────────────────────────────────────────┘
                           ↑
┌─────────────────────────────────────────────────────────────┐
│               INTELLIGENCE PLANE                            │
│  (Analytics, ML, Anomaly Detection, Events)                 │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │ Aggregation  │ Baselines    │ Anomalies    │             │
│  │ (hourly fts) │ (365 days)   │ (MAD-based)  │             │
│  └──────────────┼──────────────┼──────────────┘             │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │ Events       │ ML Training  │ Inference    │             │
│  │ (merge,det)  │ (4 models)   │ (intervals)  │             │
│  └──────────────┴──────────────┴──────────────┘             │
└─────────────────────────────────────────────────────────────┘
                           ↑
┌─────────────────────────────────────────────────────────────┐
│                   DATA PLANE                                │
│  (Ingestion, Validation, Deduplication, Storage)            │
│  ┌──────────────┬──────────────┬──────────────┐             │
│  │ OpenAQ       │ Open-Meteo   │ Validate     │             │
│  │ (1,200/hr)   │ (450/hr)     │ (quality)    │             │
│  └──────────────┼──────────────┼──────────────┘             │
│  ┌──────────────┬──────────────┐                            │
│  │ Deduplicate  │ Store        │                            │
│  │ (idempotent) │ (immutable)  │                            │
│  └──────────────┴──────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

## Technology Stack Rationale

### Data Storage
- **PostgreSQL:** Control plane, model registry, watermarks, transactions
  - Why: ACID compliance, proven reliability, operational simplicity
  - Usage: metadata, status tracking, audit log
  
- **Parquet (date-partitioned):** Immutable analytics data
  - Why: memory efficiency, columnar compression, schema evolution
  - Usage: raw air quality, weather, aggregations, features

### Processing & Orchestration
- **Python 3.12:** Core platform language
  - Why: Rich ecosystem (pandas, scikit-learn, FastAPI), data science standard
  
- **Polars:** In-memory transforms
  - Why: 10x faster than Pandas, streaming-capable, minimal memory footprint
  
- **Airflow:** Orchestration (hourly ingestion, daily backfill, weekly retraining)
  - Why: battle-tested, clear DAG semantics, retry/alerting built-in

### Analytics & ML
- **scikit-learn:** Model training (Linear, RandomForest, HistGradientBoosting)
  - Why: production-ready, explainable models, fast
  
- **NumPy:** Numerical operations (MAD, percentiles, z-scores)
  - Why: performance, universal standard

### API & Monitoring
- **FastAPI:** REST API (async, automatic validation, OpenAPI docs)
  - Why: fast, type-safe, minimal boilerplate
  
- **Pydantic:** Request/response validation
  - Why: schema enforcement, error messages

### Testing & Quality
- **pytest:** Unit, integration, performance tests (220+ tests)
  - Why: simple, parametrizable, rich plugin ecosystem

## Data Flow

### Ingestion (Hourly)
```
OpenAQ API  →  [Retry (3x)]  →  Validate (quality rules)  →  Parquet
  (1200/hr)      [Backoff]        (VALID/SUSPICIOUS/INVALID)   (dated)

Open-Meteo  →  [Retry (3x)]  →  Validate (ranges)        →  Parquet
  (450/hr)       [Backoff]        (temp, humidity, wind)       (dated)

Watermark   →  [If success]  →  Advance (next-run marker)
```

### Quality & Deduplication
```
Raw Records  →  Measurement Key  →  Deduplicate  →  Canonical
(with dups)      SHA256(source,     (idempotent)    (no doubling)
                  location,
                  pollutant,
                  time)
```

### Aggregation (Hourly)
```
Canonical Records  →  Group by hour  →  Statistics  →  Facts
(per-location)        (mean, median,     (min, max,    (1 row/location/hour)
                       min, max)          coverage)
```

### Anomaly Detection (Hourly)
```
Current Fact  →  Baseline (365-day)  →  Z-Score  →  Severity
(this hour)      (median, MAD)           (MAD-based)  (NORMAL/LOW/HIGH/EXTREME)
                                         [fallback:
                                          percentile]
```

### Events (Real-time)
```
Anomalies (HIGH+)  →  Consecutive?  →  Event  →  Merge (≤30min gap)
 (3+ in 4h window)     (≥3 HIGH?)      Detection
```

### ML Pipeline (Weekly)
```
90-Day History  →  Train/Val/Test  →  Train Models  →  Evaluate  →  Promote?
(144k records)     (70/15/15 chron)   (4 candidates)    (MAE)       (≥5% ↑)
                                                         vs. baseline
                                                         ├─ YES: Test → Prod
                                                         └─ NO: Keep current
```

### Inference (Multi-Horizon)
```
Current Features  →  Load Model  →  Predict (1h, 3h, 6h)  →  Intervals
(46 lags+         (best prod)       (empirical              (lower, upper,
 calendar)                          percentiles 5/95)       confidence 0-1)
```

### Forecast to API
```
Predictions  →  Store DB  →  API Query  →  JSON Response
(with intervals)           /forecast      ({forecasts: [...]})
```

## Key Principles

1. **Immutability:** Data written once, never modified
2. **Idempotency:** Same input → same output (watermarks prevent reprocessing)
3. **Chronological Ordering:** Strict train < val < test (no future leakage)
4. **Graceful Degradation:** Model failure → baseline forecast (never None)
5. **Observable:** Structured JSON logging, request tracing, metrics
6. **Type-Safe:** Pydantic validation on all API boundaries

## Performance Targets

| Component | Target | Status |
|-----------|--------|--------|
| OpenAQ Ingest | 10k in < 2 min | ✅ Met |
| Weather Ingest | 5k in < 2 min | ✅ Met |
| Hourly Facts | 100k in < 5 min | ✅ Met |
| ML Training | 365 days in < 2 min | ✅ Met |
| Inference | Multi-horizon < 1s | ✅ Met |
| /locations API | < 100 ms | ✅ Met |
| /forecast API | < 500 ms | ✅ Met |

## Deployment Model

- **Hourly DAG:** Continuous ingestion & aggregation (production ready)
- **Daily DAG:** Manual backfill trigger (7-90 day ranges, idempotent)
- **Weekly DAG:** Sunday 00:00 UTC retraining (optional, threshold-based)
- **API:** Always-on FastAPI server (3+ instances recommended)

## High-Level Components

```
┌─ Connectors (OpenAQ, Open-Meteo) ─────────────────┐
├─ Quality (Validation, Deduplication, Quarantine) ─┤
├─ Storage (Parquet, PostgreSQL) ───────────────────┤
├─ Analytics (Aggregation, Baselines, Anomalies) ───┤
├─ ML (Features, Training, Inference, Intervals) ───┤
├─ Events (Detection, Merging, Reporting) ──────────┤
├─ API (FastAPI, Endpoints, Responses) ─────────────┤
└─ Orchestration (Airflow DAGs, Scheduling) ────────┘
```

---

**Next:** See [Data Contracts](02-data-contracts.md) for schema definitions.
