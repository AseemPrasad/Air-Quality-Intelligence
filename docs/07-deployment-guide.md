# Air Quality Intelligence Platform: Deployment Guide

## Quick Start (Docker Compose)

### Prerequisites

- Docker & Docker Compose (v20.10+)
- Python 3.12
- PostgreSQL 15
- 8 GB RAM minimum
- 50 GB disk space (for Parquet storage)

### 1-Minute Setup

```bash
# Clone repository
git clone <repo-url>
cd air-quality-intelligence

# Create environment file
cat > .env << 'EOF'
# PostgreSQL
DATABASE_URL=postgresql://aq_user:aq_password@postgres:5432/air_quality
POSTGRES_USER=aq_user
POSTGRES_PASSWORD=aq_password
POSTGRES_DB=air_quality

# API
API_HOST=0.0.0.0
API_PORT=8000
API_LOG_LEVEL=INFO

# Airflow
AIRFLOW_HOME=/opt/airflow
AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags
AIRFLOW__WEBSERVER__SECRET_KEY=your-secret-key-change-this

# Data
DATA_DIR=/data
PARQUET_PATH=/data/parquet
LOG_PATH=/data/logs

# External APIs
OPENAQ_API_KEY=your-key
OPENMETEO_API_URL=https://api.open-meteo.com/v1
EOF

# Start services
docker-compose up -d

# Wait for services to be ready
sleep 30

# Initialize database
docker-compose exec api python -m src.aq_engine.init_db

# Check health
curl http://localhost:8000/api/system/health
```

### Docker Compose Configuration

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - aq_network

  api:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: ${DATABASE_URL}
      API_LOG_LEVEL: ${API_LOG_LEVEL}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ${DATA_DIR}:/data
      - ./src:/app/src
    command: uvicorn src.aq_engine.api.app:app --host 0.0.0.0 --port 8000 --reload
    networks:
      - aq_network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/system/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  airflow:
    build:
      context: .
      dockerfile: Dockerfile.airflow
    environment:
      AIRFLOW_HOME: ${AIRFLOW_HOME}
      AIRFLOW__CORE__DAGS_FOLDER: ${AIRFLOW__CORE__DAGS_FOLDER}
      AIRFLOW__WEBSERVER__SECRET_KEY: ${AIRFLOW__WEBSERVER__SECRET_KEY}
      AIRFLOW__CORE__LOAD_EXAMPLES: "false"
      AIRFLOW__CORE__LOAD_DEFAULT_CONNECTIONS: "false"
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ${AIRFLOW_HOME}:/opt/airflow
      - ./dags:/opt/airflow/dags
      - ${DATA_DIR}:/data
    command: >
      sh -c "
      airflow db init &&
      airflow users create --role Admin --username admin --email admin@example.com --firstname Admin --lastname User --password admin &&
      airflow webserver -p 8080
      "
    networks:
      - aq_network

volumes:
  postgres_data:

networks:
  aq_network:
    driver: bridge
```

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src ./src
COPY dags ./dags

# Expose API port
EXPOSE 8000

# Default command
CMD ["python", "-m", "src.aq_engine.main"]
```

### Dockerfile.airflow

```dockerfile
FROM apache/airflow:2.8-python3.12

USER root
RUN apt-get update && apt-get install -y postgresql-client
USER airflow

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

## Environment Variables

### Database
```bash
DATABASE_URL=postgresql://user:password@host:5432/air_quality
POSTGRES_USER=aq_user
POSTGRES_PASSWORD=aq_password
POSTGRES_DB=air_quality
```

### API Server
```bash
API_HOST=0.0.0.0
API_PORT=8000
API_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
API_WORKERS=4
API_TIMEOUT_SECONDS=30
```

### Data Paths
```bash
DATA_DIR=/data
PARQUET_PATH=/data/parquet
LOG_PATH=/data/logs
CHECKPOINT_PATH=/data/checkpoints
```

### External APIs
```bash
OPENAQ_API_KEY=your-api-key
OPENAQ_API_URL=https://api.openaq.org/v2
OPENMETEO_API_URL=https://api.open-meteo.com/v1
```

### Airflow
```bash
AIRFLOW_HOME=/opt/airflow
AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags
AIRFLOW__CORE__LOAD_EXAMPLES=false
AIRFLOW__WEBSERVER__SECRET_KEY=change-me-in-production
AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL=300
```

### Feature Flags
```bash
ENABLE_ML_TRAINING=true
ENABLE_ANOMALY_DETECTION=true
ENABLE_EVENT_DETECTION=true
MODEL_PROMOTION_THRESHOLD=0.05  # 5% MAE improvement
```

## Post-Deployment Validation

### 1. Check Services

```bash
# Check PostgreSQL
docker-compose exec postgres pg_isready -U aq_user

# Check API
curl http://localhost:8000/api/system/health

# Check Airflow
curl http://localhost:8080/api/v1/health
```

### 2. Initialize Data

```bash
# Create database schema
docker-compose exec api python -m src.aq_engine.init_db

# Seed initial locations
docker-compose exec api python -c "
from src.aq_engine.storage import LocationRepository
repo = LocationRepository()
repo.create_location(
    location_id='kolkata_001',
    name='Kolkata Center',
    city='Kolkata',
    country='India',
    latitude=22.5726,
    longitude=88.3639,
    timezone='Asia/Kolkata'
)
"
```

### 3. Test Endpoints

```bash
# List locations
curl http://localhost:8000/api/locations

# Get current observations
curl http://localhost:8000/api/locations/kolkata_001/current

# Get forecast
curl http://localhost:8000/api/locations/kolkata_001/forecast

# Check health
curl http://localhost:8000/api/system/health
```

## Production Deployment

### Kubernetes Deployment

**air-quality-api-deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aq-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: aq-api
  template:
    metadata:
      labels:
        app: aq-api
    spec:
      containers:
      - name: api
        image: air-quality-platform:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: aq-secrets
              key: database-url
        - name: API_LOG_LEVEL
          value: "INFO"
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
        livenessProbe:
          httpGet:
            path: /api/system/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/system/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
```

**air-quality-service.yaml:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: aq-api-service
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
  selector:
    app: aq-api
```

### Scaling Configuration

**Recommended Production Setup:**

```yaml
# API Servers
api:
  replicas: 3-5 (scale based on load)
  requests: 500m CPU, 512Mi RAM
  limits: 1000m CPU, 1Gi RAM

# PostgreSQL
postgres:
  storage: 100Gi SSD
  replicas: 1 (primary) + 1 (standby)
  backup: daily + WAL archiving

# Airflow Scheduler
airflow:
  replicas: 1 (primary)
  resources: 2 CPU, 4Gi RAM

# Airflow Workers
workers:
  replicas: 2-4 (scale based on DAG complexity)
  resources: 2 CPU, 4Gi RAM
```

## Monitoring & Alerts

### Prometheus Metrics

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'aq-api'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/metrics'

  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:5432']

  - job_name: 'airflow'
    static_configs:
      - targets: ['localhost:8080']
```

### Alert Rules

**Critical Alerts:**
1. API down (health check failure)
2. Database connection loss
3. Ingestion failure (> 1 hour without update)
4. Disk space < 10% remaining
5. Model performance degradation > 20%

## Troubleshooting

### Service Won't Start

**Check logs:**
```bash
docker-compose logs api
docker-compose logs postgres
docker-compose logs airflow
```

**Database connection error:**
```bash
# Verify PostgreSQL is running
docker-compose ps postgres

# Test connection manually
docker-compose exec postgres psql -U aq_user -d air_quality
```

### High Memory Usage

```bash
# Check memory limits
docker stats

# Adjust in docker-compose.yml
# Reduce --workers flag for Gunicorn
# Reduce batch sizes in ingestion
```

### Data Not Flowing

```bash
# Check Airflow DAGs
docker-compose logs airflow-scheduler

# Verify watermarks advanced
docker-compose exec postgres psql -U aq_user -d air_quality -c \
  "SELECT * FROM watermarks ORDER BY updated_at DESC LIMIT 5;"

# Check for ingestion errors
docker-compose exec postgres psql -U aq_user -d air_quality -c \
  "SELECT * FROM ingestion_log WHERE status = 'failed' LIMIT 5;"
```

### Model Training Stuck

```bash
# Monitor process
docker top airflow | grep python

# Check DAG run
docker-compose logs airflow | grep aq_model_retrain

# View training logs
tail -f data/logs/aq_model_retrain_*.log
```

## Backup & Recovery

### Daily Backup

```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_DIR="/backups/air_quality"

# Database backup
docker-compose exec -T postgres pg_dump -U aq_user air_quality | \
  gzip > "${BACKUP_DIR}/db_${DATE}.sql.gz"

# Parquet backup (copy recent files)
rsync -av --max-age=1d data/parquet/ "${BACKUP_DIR}/parquet_${DATE}/"

# Retention policy: keep 30 days
find "${BACKUP_DIR}" -name "*.gz" -mtime +30 -delete
find "${BACKUP_DIR}" -type d -mtime +30 -exec rm -rf {} \;
```

### Recovery Procedure

```bash
# Restore database
docker-compose exec -T postgres psql -U aq_user air_quality < \
  backup-2026-08-15_10-00-00.sql.gz

# Restore Parquet files
rsync -av backup/parquet_2026-08-15/ data/parquet/

# Verify data integrity
curl http://localhost:8000/api/system/quality
```

## Performance Tuning

### PostgreSQL

```sql
-- Connection pooling
max_connections = 100
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 16MB

-- Indexes
CREATE INDEX CONCURRENTLY idx_new_index ON table(...);

-- Autovacuum
autovacuum = on
autovacuum_naptime = 1min
autovacuum_vacuum_scale_factor = 0.1
```

### Python/Uvicorn

```bash
# Increase workers based on CPU cores
--workers 4

# Adjust timeout
--timeout 120

# Enable access logs
--access-log
```

### Parquet Storage

```bash
# Compression (in code)
parquet_options = {
    'compression': 'snappy',  # or 'gzip'
    'row_group_size': 64 * 1024 * 1024  # 64MB
}
```

## Version Management

### Semantic Versioning

```
Major.Minor.Patch
1.2.3
│ │ └─ Bug fixes, performance
│ └─── New features
└───── Breaking changes
```

### Upgrade Procedure

```bash
# 1. Backup everything
./backup.sh

# 2. Update images
docker pull air-quality-platform:2.0.0

# 3. Update compose file
git pull origin main

# 4. Run migrations
docker-compose exec api python -m src.aq_engine.migrate

# 5. Verify
curl http://localhost:8000/api/system/health

# 6. Rolling restart (Kubernetes)
kubectl rollout restart deployment/aq-api
```

---

**Next:** See [Runbook](08-runbook.md) for operational procedures.
