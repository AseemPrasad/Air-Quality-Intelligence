# Docker and Deployment Guide

## Overview

The Air Quality Intelligence Platform is fully containerized with optimized Docker images and a production-ready docker-compose configuration.

**Key Features:**
- Multi-stage builds for minimal image size
- Non-root user (`aqworker`) for security
- Resource limits (1-3GB per service)
- Health checks for all services
- Structured JSON logging
- Startup < 2 minutes

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Compose Network                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ PostgreSQL   │  │   Airflow    │  │   FastAPI    │ │
│  │  (Control)   │  │ Scheduler/UI │  │    API       │ │
│  │  5432        │  │  8080        │  │    8000      │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                         │
│  ┌──────────────┐                                      │
│  │  Streamlit   │                                      │
│  │  Dashboard   │                                      │
│  │    8501      │                                      │
│  └──────────────┘                                      │
│                                                         │
│  Network: aq-net (bridge)                             │
│  Volume: aq-postgres-data (named)                     │
│          ./data (mounted)                              │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Docker Images

### 1. Dockerfile.api (FastAPI Server)

**Base:** `python:3.12.1-slim-bookworm`  
**Size:** ~400MB (optimized)  
**User:** `aqworker` (non-root)

```dockerfile
# Multi-stage build
Builder Stage:
  - Compile Python dependencies
  - Install build tools (removed in runtime)

Runtime Stage:
  - Minimal Python environment
  - Only runtime dependencies (libpq5, curl)
  - Copy compiled wheels from builder
  - Health check: GET /api/system/health
```

**Resource Limits:**
```yaml
limits:
  cpus: "2"
  memory: 1G
reserves:
  cpus: "1"
  memory: 512M
```

### 2. Dockerfile.dashboard (Streamlit)

**Base:** `python:3.12.1-slim-bookworm`  
**Size:** ~450MB (optimized)  
**User:** `aqworker` (non-root)

```dockerfile
# Multi-stage build (same pattern as API)
Builder Stage:
  - Compile Python + Streamlit dependencies
  - Install build tools

Runtime Stage:
  - Minimal Streamlit environment
  - Health check: GET http://localhost:8501/_stcore/health
  - Environment: STREAMLIT_SERVER_HEADLESS=true
```

**Resource Limits:**
```yaml
limits:
  cpus: "1"
  memory: 512M
reserves:
  cpus: "0.5"
  memory: 256M
```

### 3. Dockerfile.worker (Airflow)

**Base:** `python:3.12.1-slim-bookworm`  
**Size:** ~500MB (optimized)  
**User:** `aqworker` (non-root)

```dockerfile
# Multi-stage build
Builder Stage:
  - Compile Airflow + dependencies
  - Install git for DAG pulls

Runtime Stage:
  - Airflow environment
  - Health check: airflow jobs check-sla
  - Can run as: scheduler, webserver, or worker
```

**Resource Limits:**
```yaml
# Scheduler
limits:
  cpus: "2"
  memory: 3G
reserves:
  cpus: "1"
  memory: 1G

# Webserver
limits:
  cpus: "1"
  memory: 1G
reserves:
  cpus: "0.5"
  memory: 512M
```

## Docker Compose Services

### PostgreSQL (postgres)

```yaml
Image: postgres:15.4-alpine3.18
Port: 5432:5432
User: aqadmin (configurable)
Database: aq_control (configurable)
Memory: 2GB limit, 1GB reserve
Volumes:
  - aq-postgres-data:/var/lib/postgresql/data
  - ./docker/postgres-init:/docker-entrypoint-initdb.d
Health Check: pg_isready (10s interval)
```

**Optimizations:**
```
shared_buffers=256MB
max_connections=200
effective_cache_size=1GB
maintenance_work_mem=64MB
work_mem=10MB
```

### Airflow Init (airflow-init)

```yaml
Image: Built from Dockerfile.worker
Runs Once: Initializes database & creates admin user
Admin Credentials: admin / admin (CHANGE IN PRODUCTION)
Depends On: postgres (healthy)
Restart: no (one-time only)
```

### Airflow Scheduler (airflow-scheduler)

```yaml
Image: Built from Dockerfile.worker
Port: Internal only (no exposed port)
Memory: 3GB limit, 1GB reserve
Command: airflow scheduler
Depends On: airflow-init, postgres
Health Check: airflow jobs check-sla
Volumes:
  - ./dags:/app/dags
  - ./logs:/app/logs
  - ./data:/app/data
```

### Airflow Webserver (airflow-webserver)

```yaml
Image: Built from Dockerfile.worker
Port: 8080:8080
Memory: 1GB limit, 512MB reserve
Command: airflow webserver --port 8080
Admin URL: http://localhost:8080
Depends On: airflow-scheduler
Health Check: curl http://localhost:8080/health
```

### FastAPI API (api)

```yaml
Image: Built from Dockerfile.api
Port: 8000:8000
Memory: 1GB limit, 512MB reserve
Environment:
  - DATABASE_URL: postgresql+psycopg://...@postgres:5432/...
  - API_LOG_LEVEL: INFO
Depends On: postgres
Health Check: curl http://localhost:8000/api/system/health
API Docs: http://localhost:8000/docs
```

### Streamlit Dashboard (dashboard)

```yaml
Image: Built from Dockerfile.dashboard
Port: 8501:8501
Memory: 512MB limit, 256MB reserve
Environment:
  - DATABASE_URL: postgresql+psycopg://...
  - API_URL: http://api:8000
Depends On: postgres, api
Health Check: curl http://localhost:8501/_stcore/health
Dashboard URL: http://localhost:8501
```

## Configuration

### Environment Variables (.env)

**Database:**
```bash
POSTGRES_USER=aqadmin              # Default username
POSTGRES_PASSWORD=changeme         # ⚠️ CHANGE IN PRODUCTION
POSTGRES_DB=aq_control             # Database name
```

**API:**
```bash
API_LOG_LEVEL=INFO                 # DEBUG, INFO, WARNING, ERROR
ENVIRONMENT=production             # development, staging, production
```

**Airflow:**
```bash
AIRFLOW_HOME=/airflow
AIRFLOW__WEBSERVER__SECRET_KEY=... # ⚠️ GENERATE IN PRODUCTION
```

**External APIs:**
```bash
OPENAQ_API_KEY=your_key_here       # OpenAQ API key
```

### Creating .env File

```bash
# Copy template
cp .env.example .env

# Edit with your values
nano .env

# Key changes for production:
# 1. POSTGRES_PASSWORD: Use strong password
# 2. AIRFLOW__WEBSERVER__SECRET_KEY: Generate: python -c "import secrets; print(secrets.token_urlsafe(30))"
# 3. OPENAQ_API_KEY: Set to actual API key
# 4. ENVIRONMENT: Set to "production"
```

## Startup & Operations

### Quick Start

```bash
# 1. Create environment file
cp .env.example .env

# 2. Start all services
docker-compose up -d

# 3. Wait for startup (< 2 minutes)
docker-compose logs -f

# 4. Check health
docker/health-check.sh

# 5. Access services
# API:      http://localhost:8000
# Airflow:  http://localhost:8080
# Dashboard: http://localhost:8501
```

### Verify Services

```bash
# Show all services status
docker-compose ps

# Check specific service
docker-compose ps postgres

# View logs
docker-compose logs api
docker-compose logs -f airflow-scheduler

# Follow all logs
docker-compose logs -f
```

### Health Check Script

```bash
# Run health check
docker/health-check.sh

# Output includes:
# - Service status (running/stopped)
# - Health status (healthy/unhealthy/starting)
# - API endpoint responses
# - Database connectivity
# - Service URLs
# - Resource usage

# Exit codes:
# 0 = All healthy
# 1 = Any service unhealthy
```

## Performance

### Startup Time

```
Typical startup sequence:
1. PostgreSQL initializes:        10-15 seconds
2. Airflow init (first run):      20-30 seconds
3. Airflow scheduler starts:       10-15 seconds
4. API server starts:              5-10 seconds
5. Dashboard initializes:          10-15 seconds

Total: < 2 minutes (first run)
       < 1 minute (subsequent runs)
```

### Resource Usage

**Total Memory (all services):**
- Soft limit: 4GB
- Hard limit: 8GB
- Typical usage: 3-4GB

**Breakdown:**
- PostgreSQL: 1-2GB
- Airflow Scheduler: 800MB-1GB
- Airflow Webserver: 500MB-800MB
- API: 300-500MB
- Dashboard: 200-400MB

**CPU Usage:**
- Normal: 10-20% (4 cores)
- Peak (training): 50-80%

## Backup & Recovery

### PostgreSQL Backup

```bash
# Backup entire database
docker-compose exec -T postgres pg_dump -U aqadmin aq_control | \
  gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Restore from backup
zcat backup_20260815_100000.sql.gz | \
  docker-compose exec -T postgres psql -U aqadmin aq_control
```

### Data Volume Backup

```bash
# Backup data directory
tar czf data_backup_$(date +%Y%m%d_%H%M%S).tar.gz ./data

# Restore
tar xzf data_backup_20260815_100000.tar.gz
```

### Container Cleanup

```bash
# Stop all services
docker-compose stop

# Remove containers
docker-compose rm -f

# Remove volumes (CAREFUL - deletes data!)
docker volume rm aq-postgres-data

# Remove images
docker-compose down --rmi all
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker-compose logs service_name

# Common issues:
# 1. Port already in use: lsof -i :8000
# 2. Insufficient memory: docker system df
# 3. Volume issues: docker volume ls
```

### Database Connection Failed

```bash
# Verify PostgreSQL is running
docker-compose ps postgres

# Test connection
docker-compose exec postgres psql -U aqadmin -d aq_control -c "SELECT 1"

# Check PostgreSQL logs
docker-compose logs postgres
```

### API Not Responding

```bash
# Check API logs
docker-compose logs api

# Test health endpoint
curl http://localhost:8000/api/system/health

# Check database connectivity from API
docker-compose exec api python -c \
  "from src.aq_engine.storage.db import DatabaseConnection; \
   db = DatabaseConnection('${DATABASE_URL}'); \
   print('Connected!' if db.is_connected() else 'Failed')"
```

### Airflow Issues

```bash
# Check scheduler status
docker-compose logs airflow-scheduler

# List DAGs
docker-compose exec airflow-scheduler airflow dags list

# Trigger DAG manually
docker-compose exec airflow-scheduler airflow dags trigger aq_hourly_ingest

# Access webserver logs
docker-compose logs airflow-webserver
```

## Production Deployment

### Pre-Deployment Checklist

- [ ] Generate new `POSTGRES_PASSWORD` (min 16 chars)
- [ ] Generate `AIRFLOW__WEBSERVER__SECRET_KEY` (use `secrets` module)
- [ ] Set actual `OPENAQ_API_KEY`
- [ ] Change `ENVIRONMENT=production`
- [ ] Review resource limits for your hardware
- [ ] Test backup/restore procedures
- [ ] Setup log rotation and monitoring
- [ ] Configure external reverse proxy (nginx/caddy)
- [ ] Enable HTTPS/TLS
- [ ] Setup monitoring (Prometheus/Grafana)

### Reverse Proxy (nginx)

```nginx
upstream api {
    server api:8000;
}

upstream dashboard {
    server dashboard:8501;
}

upstream airflow {
    server airflow-webserver:8080;
}

server {
    listen 80;
    server_name aq.example.com;
    
    # API
    location /api {
        proxy_pass http://api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # Dashboard
    location / {
        proxy_pass http://dashboard;
    }
    
    # Airflow
    location /airflow {
        proxy_pass http://airflow;
    }
}
```

## Monitoring

### Health Monitoring

```bash
# Continuous monitoring
watch -n 5 'docker/health-check.sh'

# Log monitoring
docker-compose logs --follow --tail=50
```

### Metrics Export

```bash
# Prometheus metrics from API
curl http://localhost:8000/metrics

# Database metrics
docker-compose exec postgres psql -U aqadmin -d aq_control \
  -c "SELECT datname, numbackends FROM pg_stat_database"
```

## Updates & Upgrades

### Update Application Code

```bash
# 1. Pull latest code
git pull origin main

# 2. Rebuild images
docker-compose build

# 3. Restart services
docker-compose up -d

# 4. Verify health
docker/health-check.sh
```

### Update Dependencies

```bash
# 1. Update pyproject.toml
# 2. Rebuild images
docker-compose build --no-cache

# 3. Restart services
docker-compose restart
```

---

**Next:** See [CLI and Configuration](CLI-and-Configuration.md) for command-line usage.
