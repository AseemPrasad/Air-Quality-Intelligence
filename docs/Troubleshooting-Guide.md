# Troubleshooting Guide

Common issues and solutions for the Air Quality Intelligence Platform.

## Table of Contents

- [Installation Issues](#installation-issues)
- [Database Connection Problems](#database-connection-problems)
- [API Issues](#api-issues)
- [Ingestion Problems](#ingestion-problems)
- [Airflow Issues](#airflow-issues)
- [Docker Problems](#docker-problems)
- [Performance Issues](#performance-issues)
- [Data Quality Issues](#data-quality-issues)

## Installation Issues

### Python Version Mismatch

**Problem:** Error during pip install or import errors.

```
ERROR: Package requires Python >=3.12
```

**Solution:**
```bash
# Check Python version
python --version

# Install Python 3.12 if needed
# Then use venv
python3.12 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Dependency Conflicts

**Problem:** Conflicting package versions during installation.

```
ERROR: Cannot install aq-engine because these package versions have conflicting dependencies
```

**Solution:**
```bash
# Clean install
pip uninstall aq-engine
rm -rf build/ dist/ *.egg-info
pip install -e ".[dev]" --no-cache-dir

# Or use fresh virtual environment
rm -rf venv
python3.12 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Missing System Dependencies

**Problem:** Build fails for binary packages.

```
ERROR: Failed building wheel for psycopg
```

**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install python3-dev libpq-dev build-essential

# macOS
brew install postgresql

# Then retry installation
pip install -e ".[dev]"
```

## Database Connection Problems

### Cannot Connect to PostgreSQL

**Problem:** Database connection timeouts or refused connections.

```
DatabaseError: could not connect to server: Connection refused
```

**Solution:**

1. Check if PostgreSQL is running:
```bash
# Docker
docker ps | grep postgres

# If not running
docker-compose up -d postgres
```

2. Verify connection parameters:
```bash
# Check .env file
cat .env | grep POSTGRES

# Test connection
psql -h localhost -U aqadmin -d aq_control
```

3. Check firewall:
```bash
# Ensure port 5432 is accessible
telnet localhost 5432
```

### Database Does Not Exist

**Problem:** Database aq_control not found.

```
DatabaseError: database "aq_control" does not exist
```

**Solution:**
```bash
# Connect to PostgreSQL
psql -h localhost -U postgres

# Create database
CREATE DATABASE aq_control;

# Grant privileges
GRANT ALL PRIVILEGES ON DATABASE aq_control TO aqadmin;
```

### Migration Errors

**Problem:** Schema mismatch or migration failures.

```
sqlalchemy.exc.ProgrammingError: relation "source" does not exist
```

**Solution:**
```bash
# Run migrations
alembic upgrade head

# Or recreate schema
psql -h localhost -U aqadmin -d aq_control < sql/schema.sql

# Verify tables exist
psql -h localhost -U aqadmin -d aq_control -c "\dt"
```

### Connection Pool Exhausted

**Problem:** Too many connections to database.

```
DatabaseError: connection pool exhausted
```

**Solution:**

1. Check current connections:
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'aq_control';
```

2. Increase pool size in config:
```yaml
# configs/default.yaml
database:
  pool_size: 20  # Increase from 10
  max_overflow: 40  # Increase from 20
```

3. Close idle connections:
```sql
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE datname = 'aq_control' AND state = 'idle';
```

## API Issues

### API Won't Start

**Problem:** FastAPI fails to start or crashes immediately.

```
ImportError: cannot import name 'app' from 'aq_engine.api.main'
```

**Solution:**

1. Check imports:
```bash
# Test import
python -c "from aq_engine.api.main import app; print('OK')"
```

2. Check logs:
```bash
# View API logs
docker-compose logs api

# Or direct run for debugging
uvicorn aq_engine.api.main:app --reload --log-level debug
```

3. Verify port not in use:
```bash
# Check if port 8000 is occupied
lsof -i :8000

# Kill process if needed
kill -9 <PID>
```

### 500 Internal Server Error

**Problem:** API returns 500 errors for all requests.

**Solution:**

1. Check API logs:
```bash
tail -f logs/aq_engine.log
```

2. Verify database connectivity:
```bash
# Test health endpoint
curl http://localhost:8000/health
```

3. Check for missing data:
```sql
-- Verify source records exist
SELECT * FROM source;
```

### CORS Errors in Browser

**Problem:** Browser blocks API requests due to CORS.

```
Access to fetch blocked by CORS policy
```

**Solution:**

Update CORS origins in docker-compose.yml:
```yaml
environment:
  CORS_ORIGINS: "http://localhost:3000,http://localhost:8501,https://your-domain.com"
```

Restart API:
```bash
docker-compose restart api
```

### Rate Limit Issues

**Problem:** Receiving 429 Too Many Requests.

```json
{
  "error": "Rate limit exceeded. Maximum 100 requests per minute."
}
```

**Solution:**

1. Implement exponential backoff:
```python
import time

def make_request_with_backoff(url, max_retries=3):
    for i in range(max_retries):
        response = requests.get(url)
        if response.status_code != 429:
            return response
        
        retry_after = int(response.headers.get('Retry-After', 60))
        time.sleep(retry_after)
    
    raise Exception("Rate limit exceeded after retries")
```

2. Or adjust rate limit in code if needed for high-volume scenarios

## Ingestion Problems

### OpenAQ API Key Invalid

**Problem:** OpenAQ ingestion fails with authentication error.

```
IngestionFailed: OpenAQ API authentication failed: invalid API key
```

**Solution:**

1. Verify API key:
```bash
# Check .env file
cat .env | grep OPENAQ_API_KEY

# Test key
curl -H "X-API-Key: your_key" https://api.openaq.org/v3/locations
```

2. Get new key if needed:
- Visit https://openaq.org/
- Register for API access
- Update .env file

3. Restart ingestion:
```bash
docker-compose restart worker
```

### No Data Ingested

**Problem:** Ingestion runs but writes zero records.

**Solution:**

1. Check connector logs:
```bash
docker-compose logs worker | grep -A 10 "ingest_openaq"
```

2. Verify API responses:
```bash
# Test OpenAQ API directly
curl "https://api.openaq.org/v3/locations?country=IN&city=Kolkata"
```

3. Check data validation:
```bash
# Look for rejected records
grep "records_rejected" logs/aq_engine.log
```

4. Verify location configuration:
```yaml
# configs/sources/openaq.yaml
location:
  city: "Kolkata"  # Ensure matches API data
  country: "India"
```

### Duplicate Records

**Problem:** Same observations appear multiple times.

**Solution:**

1. Check deduplication:
```bash
# View Parquet files
python -c "import polars as pl; df = pl.read_parquet('data/raw/openaq/year=2026/month=09/day=27/*.parquet'); print(df.shape)"
```

2. Verify watermark:
```sql
SELECT source_name, watermark_end 
FROM ingestion_run 
WHERE status = 'success'
ORDER BY finished_at DESC
LIMIT 5;
```

3. Manual cleanup if needed:
```bash
# Remove duplicates from specific date
rm -rf data/raw/openaq/year=2026/month=09/day=27/
# Then re-ingest
aq ingest --source openaq --start-date 2026-09-27 --end-date 2026-09-27
```

### Ingestion Timeout

**Problem:** Connector times out fetching data.

```
IngestionFailed: Request timeout after 30 seconds
```

**Solution:**

Increase timeout in config:
```yaml
# configs/sources/openaq.yaml
openaq:
  timeout_seconds: 60  # Increase from 30
```

Or split into smaller time ranges:
```bash
# Instead of large backfill
aq backfill --source openaq --start 2026-01-01 --end 2026-09-27

# Use daily ingestion
aq ingest --source openaq --start-date 2026-09-27
```

## Airflow Issues

### Airflow Web UI Not Accessible

**Problem:** Cannot access Airflow at http://localhost:8080

**Solution:**

1. Check if Airflow is running:
```bash
docker ps | grep airflow
```

2. Start if needed:
```bash
docker-compose up -d airflow-webserver airflow-scheduler
```

3. Check logs:
```bash
docker-compose logs airflow-webserver
```

4. Verify port mapping:
```bash
docker port aq-airflow-webserver
```

### DAG Not Appearing

**Problem:** DAG files exist but don't show in UI.

**Solution:**

1. Check DAG syntax:
```bash
# Test DAG file
python dags/aq_hourly_ingest_dag.py
```

2. Verify DAG folder:
```bash
# Check if mounted correctly
docker exec aq-airflow-webserver ls -la /app/dags
```

3. Refresh DAGs:
```bash
# Restart scheduler
docker-compose restart airflow-scheduler
```

4. Check for errors:
```bash
# View scheduler logs
docker-compose logs airflow-scheduler | grep ERROR
```

### DAG Task Fails

**Problem:** Airflow task shows failed status.

**Solution:**

1. View task logs in UI:
- Click on failed task
- View log output
- Check error message

2. Or check logs directly:
```bash
docker-compose logs airflow-scheduler | grep -A 20 "ERROR"
```

3. Common fixes:
```bash
# Clear failed task
airflow tasks clear aq_hourly_ingest -t ingest_openaq -s 2026-09-27

# Or mark as success
airflow tasks state aq_hourly_ingest ingest_openaq 2026-09-27T00:00:00+00:00 success
```

### Scheduler Not Running Tasks

**Problem:** DAG is active but tasks never execute.

**Solution:**

1. Check scheduler status:
```bash
docker-compose logs airflow-scheduler | tail -20
```

2. Verify DAG is unpaused:
```bash
airflow dags unpause aq_hourly_ingest
```

3. Check schedule interval:
```python
# In DAG file
schedule_interval="0 * * * *"  # Hourly at minute 0
```

4. Restart scheduler:
```bash
docker-compose restart airflow-scheduler
```

## Docker Problems

### Container Won't Start

**Problem:** Docker container exits immediately.

**Solution:**

1. Check logs:
```bash
docker-compose logs <service-name>
```

2. Check exit code:
```bash
docker-compose ps
```

3. Verify dependencies:
```bash
# Ensure postgres is healthy
docker-compose ps postgres
```

4. Rebuild if needed:
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Out of Disk Space

**Problem:** Docker fails with disk space error.

```
Error: no space left on device
```

**Solution:**

1. Check disk usage:
```bash
df -h
docker system df
```

2. Clean up:
```bash
# Remove unused images
docker image prune -a

# Remove volumes
docker volume prune

# Full cleanup
docker system prune -a --volumes
```

3. Clear old Parquet files:
```bash
# Keep last 90 days only
find data/raw -type f -mtime +90 -delete
```

### Port Already in Use

**Problem:** Cannot start container, port in use.

```
Error: bind: address already in use
```

**Solution:**

1. Find process using port:
```bash
# For port 8000
lsof -i :8000

# Or
netstat -tulpn | grep 8000
```

2. Kill process:
```bash
kill -9 <PID>
```

3. Or change port in docker-compose.yml:
```yaml
ports:
  - "8001:8000"  # Map to different host port
```

### Network Issues

**Problem:** Containers cannot communicate.

**Solution:**

1. Check network:
```bash
docker network ls
docker network inspect aq-net
```

2. Recreate network:
```bash
docker-compose down
docker network rm aq-net
docker-compose up -d
```

3. Verify service names:
```bash
# Containers should use service names
# e.g., postgres not localhost
DATABASE_URL=postgresql://user:pass@postgres:5432/db
```

## Performance Issues

### Slow Query Performance

**Problem:** API responses are slow.

**Solution:**

1. Check database indexes:
```sql
-- Verify indexes exist
\di

-- Add missing indexes
CREATE INDEX idx_source_name ON source(source_name);
CREATE INDEX idx_location_code ON location(location_code);
```

2. Analyze query plans:
```sql
EXPLAIN ANALYZE 
SELECT * FROM source WHERE source_name = 'openaq';
```

3. Update statistics:
```sql
ANALYZE;
VACUUM ANALYZE;
```

### High Memory Usage

**Problem:** System runs out of memory.

**Solution:**

1. Check memory usage:
```bash
docker stats

# Or system-wide
free -h
htop
```

2. Reduce memory footprint:
```yaml
# In docker-compose.yml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 1G
```

3. Optimize Postgres:
```yaml
# In docker-compose.yml
POSTGRES_INITDB_ARGS: >-
  -c shared_buffers=128MB
  -c effective_cache_size=512MB
```

### Large Parquet Files

**Problem:** Parquet files growing too large.

**Solution:**

1. Check file sizes:
```bash
du -sh data/raw/*/*/*/*
```

2. Implement retention policy:
```bash
# Delete data older than 90 days
find data/raw -type f -mtime +90 -delete
```

3. Compress older files:
```bash
# Archive old data
tar -czf data/archive/2026-Q1.tar.gz data/raw/*/year=2026/month={01,02,03}
rm -rf data/raw/*/year=2026/month={01,02,03}
```

## Data Quality Issues

### High Rejection Rate

**Problem:** Many records rejected during validation.

**Solution:**

1. Check rejection reasons:
```bash
grep "quality_flag" logs/aq_engine.log | sort | uniq -c
```

2. Review validation rules:
```python
# Check QualityValidator thresholds
# Adjust if too strict
```

3. Inspect rejected data:
```bash
# Check quarantine if implemented
ls -la data/quarantine/
```

### Missing Data Gaps

**Problem:** Time series has gaps.

**Solution:**

1. Check ingestion status:
```sql
SELECT source_name, requested_start, requested_end, status
FROM ingestion_run
WHERE status != 'success'
ORDER BY requested_start DESC;
```

2. Backfill missing dates:
```bash
# Identify gaps
aq ingest --source openaq --start-date 2026-09-20 --end-date 2026-09-27
```

3. Verify source availability:
```bash
# Check if source was down
curl -I https://api.openaq.org/v3/locations
```

### Stale Data

**Problem:** Latest observations are old.

**Solution:**

1. Check ingestion schedule:
```bash
# Verify DAG is running
airflow dags list
airflow dags next-execution aq_hourly_ingest
```

2. Manual trigger:
```bash
aq ingest --source openaq
```

3. Check watermark:
```sql
SELECT source_name, watermark_end, finished_at
FROM ingestion_run
WHERE status = 'success'
ORDER BY finished_at DESC
LIMIT 5;
```

## Getting More Help

### Enable Debug Logging

```yaml
# configs/logging.yaml
root:
  level: DEBUG  # Change from INFO
```

Or via environment:
```bash
export LOG_LEVEL=DEBUG
```

### Collect Diagnostic Information

```bash
# System info
uname -a
python --version
docker --version

# Service status
docker-compose ps
docker-compose logs --tail=100

# Database status
psql -h localhost -U aqadmin -d aq_control -c "SELECT version();"

# API health
curl http://localhost:8000/health
```

### Check Logs

```bash
# Application logs
tail -f logs/aq_engine.log

# Docker logs
docker-compose logs -f

# Specific service
docker-compose logs -f api

# Airflow logs
docker-compose logs -f airflow-scheduler
```

## Related Documentation

- [Deployment Guide](07-deployment-guide.md)
- [API Usage Guide](API-Usage-Guide.md)
- [System Architecture](01-system-architecture.md)
- [CLI Reference](CLI-QUICK-REFERENCE.md)
