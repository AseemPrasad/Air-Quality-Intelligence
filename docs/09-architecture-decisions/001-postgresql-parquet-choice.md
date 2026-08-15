# ADR 001: PostgreSQL + Parquet for Dual Storage

**Date:** 2026-08-15  
**Status:** ACCEPTED  
**Stakeholders:** Architecture Team, Data Engineering

## Context

The Air Quality Intelligence Platform needs to store 50+ GB of air quality measurements, weather observations, and derived features. The system must support:

1. **Real-time queries** for API responses (milliseconds)
2. **Batch analytics** for model training (minutes)
3. **Idempotent re-runs** without data doubling
4. **Historical backfill** over arbitrary date ranges
5. **Audit trails** for data governance
6. **Transactional consistency** for critical operations

## Decision

**Adopt dual-storage architecture:**
- **PostgreSQL (control plane):** Metadata, watermarks, model registry, transactions
- **Parquet (analytics data):** Immutable, date-partitioned, columnar storage

## Rationale

### Why Not Single Storage?

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| **Pure Relational** (PostgreSQL) | ACID, transactions, easy queries | Inefficient at scale, expensive storage, slow analytics | ❌ |
| **Pure Columnar** (Parquet) | Fast analytics, small footprint, native to Python | No transactions, no primary keys, manual bookkeeping | ❌ |
| **Dual Storage** | Best of both worlds | More complex operations | ✅ |

### PostgreSQL for Control Plane

**Why PostgreSQL?**

1. **ACID Guarantees**
   - Watermarks must not be lost: if crash during `UPDATE watermarks`, next run should retry cleanly
   - Model registry updates must be atomic: candidate→production transition is all-or-nothing

2. **Proven Reliability**
   - 25+ years in production
   - Mature replication, backup, monitoring tooling
   - Largest operational knowledge base

3. **Operational Simplicity**
   - Single source of truth for metadata
   - Works in any environment (local, Docker, cloud)
   - Minimal operational overhead

**What lives in PostgreSQL?**
```
- locations (3 rows)
- stations (50 rows)
- watermarks (1 row per source per location) ← Critical
- hourly_facts (millions, recent only) ← For API queries
- baselines (3 × 12 × 24 rows) ← For anomaly detection
- anomalies (1M+ rows) ← For events
- events (10k rows) ← For user queries
- models (10-20 versions) ← Model registry
- predictions (10M rows) ← Forecast results
- data_quality_log (1M+ rows) ← Audit trail
```

**Why not put all data in PostgreSQL?**
- 50+ GB table → slow table scans
- Analytics queries (aggregations, joins) expensive
- ML training loads 100k records → takes minutes vs. seconds with Parquet

### Parquet for Analytics Data

**Why Parquet?**

1. **Columnar Compression**
   - PM2.5 values are numeric → compresses to 5-10% of original size
   - Query "all PM2.5 for August" → read only PM2.5 column, not entire row
   - 50 GB → 5-10 GB on disk

2. **Immutable by Design**
   - Date-partitioned files: `/data/parquet/2026-08-15/*.parquet`
   - Once written, never modified (append-only)
   - Simplifies backup/recovery

3. **Python Integration**
   - Native support via Polars, pandas, PyArrow
   - No serialization overhead
   - In-process analytics

4. **Watermark-Based Reprocessing**
   - Watermark points to last-processed timestamp
   - Rerun from watermark → re-read same Parquet files
   - Same input → same output (idempotent)

**What lives in Parquet?**
```
/data/parquet/
├── raw_openaq/2026-08-14/*.parquet    ← ~1200 records
├── raw_weather/2026-08-14/*.parquet   ← ~450 records
├── facts/2026-08-14/*.parquet         ← Aggregated hourly
└── features/2026-08-14/*.parquet      ← 46 features per record
```

**Parquet file structure:**
```python
# Raw data: day-partitioned
parquet_path = f"/data/parquet/raw_openaq/{date}/*.parquet"
df = pl.scan_parquet(parquet_path)
# ← Lazy scan, doesn't load until .collect()

# Features: day-partitioned, organized by location
features_path = f"/data/parquet/features/{date}/*.parquet"
# Each file is location-specific for parallelization
```

## Implementation

### Data Flow

```
OpenAQ API (1200 records/hour)
    ↓
PostgreSQL watermark (last processed: 2026-08-15 10:00)
    ↓
Fetch new records (10:00 to 11:00)
    ↓
Validation (VALID/SUSPICIOUS/INVALID)
    ↓
Deduplicate (SHA256 measurement_key)
    ↓ Store both places:
    ├→ PostgreSQL (recent, query-optimized)
    └→ Parquet (immutable, analytics)
    ↓
Update watermark (11:00)
    ↓
[Idempotency achieved: rerun with same watermark = same output]
```

### Idempotency via Watermarks

**Problem:** Network failure during ingestion

```
Scenario 1: HTTP 200, but PostgreSQL INSERT fails
→ Watermark NOT advanced
→ Next run retries same timestamp
→ Duplicate prevention: measurement_key hash catches it

Scenario 2: HTTP 200, watermark partially updated
→ Transaction rolled back (ACID)
→ Watermark unchanged
→ Next run retries cleanly
```

**Code pattern:**
```python
try:
    # Fetch data
    records = fetch_openaq(watermark.last_processed_time)
    
    # Ingest
    for record in records:
        # Deduplicate
        if not exists_by_measurement_key(record):
            insert_to_postgres(record)
            insert_to_parquet(record)
    
    # Atomic: only if all succeeded
    watermark.update(new_time)
    db.commit()
except Exception as e:
    db.rollback()
    raise
```

## Tradeoffs

### Complexity

**Cost:** More operations (2 writes per record)

```
Faster (PostgreSQL only):     1 write
Slower (PostgreSQL + Parquet): 2 writes, 50% latency increase
Mitigation: Async writes, batching
```

**Cost:** Schema sync between stores

```
If schema changes:
- Update PostgreSQL DDL
- Update Parquet schema
- Both must match
Mitigation: Automated migrations, schema registry
```

### Performance

**Benefits:**
- API queries: 50ms (PostgreSQL indexed scans)
- Training queries: 10x faster (Parquet columnar reads)

**Costs:**
- Ingestion: 2x writes (negligible at ~1200 records/hour)
- Operational: monitor 2 systems

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Watermark lost** | Data duplication | PostgreSQL backup + WAL archiving |
| **Parquet schema drift** | Query failures | Schema validation on write |
| **Storage exhaustion** | System down | Retention policy: auto-delete > 3 years |
| **PostgreSQL crash** | API unavailable | Replication + daily backups |

## Alternatives Considered

### 1. Single PostgreSQL (Rejected)
```
Pros: One system, simpler operations
Cons: 50 GB table → slow analytics, expensive
Cost: 10x higher storage, slower training
```

### 2. Single Parquet (Rejected)
```
Pros: Fast analytics, cheap storage
Cons: No transactions, manual idempotency bookkeeping
Cost: Watermark bugs, data duplication risk
```

### 3. Data Warehouse (Redshift/BigQuery) (Rejected)
```
Pros: Scalable, managed
Cons: Vendor lock-in, monthly cost ~$500-2000
Tradeoff: Not justified for current scale
```

## Metrics & Success Criteria

- ✅ Ingestion idempotency: < 1 duplicate per 10k records
- ✅ API P95 latency: < 500 ms (PostgreSQL queries)
- ✅ Training throughput: 100k features < 2 min (Parquet reads)
- ✅ Storage efficiency: < 10 GB for 50 GB raw data (Parquet compression)

## Future Considerations

1. **Scale to multi-region:** Replicate PostgreSQL across regions, use S3 for Parquet
2. **Scale to 1TB:** Consider read-replica for analytics queries
3. **Switch to DuckDB:** If operational overhead of PostgreSQL becomes burden

---

**Related:** [[002-polars-choice]], [[004-anomaly-detection-mad]]
