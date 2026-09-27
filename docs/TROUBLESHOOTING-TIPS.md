# Air Quality Intelligence - Troubleshooting & Error Guide

This guide covers common runtime issues, environment configuration errors, and pipeline debugging strategies for the Air Quality Intelligence engine.

## 1. Environment and Connection Errors

### Database Connection Refused
* **Symptom:** The CLI throws a connection error when running ingestion or aggregation tasks.
* **Cause:** PostgreSQL is either not running or the `DATABASE_URL` environment variable is pointing to an incorrect host/port.
* **Resolution:** 
  1. Verify your database service status.
  2. Check your `.env` file configuration:
     ```bash
     DATABASE_URL=postgresql://user:password@localhost:5432/air_quality_db
     ```

### Missing OpenAQ API Key
* **Symptom:** Ingestion from OpenAQ fails with authentication or rate-limit exceptions.
* **Resolution:** Ensure your API key is correctly exported or defined in your environment:
  ```bash
  export OPENAQ_API_KEY="your_api_key_here"
  ```
  
## 2. Pipeline Execution Issues

### Missing Date Parameter
* **Symptom:** Commands like `aq validate` or `aq aggregate` fail with a missing argument error.
* **Resolution:** Always specify the target date using ISO 8601 format (`YYYY-MM-DD`):
  ```bash
  aq validate --date 2026-08-15
  ```
  ### Configuration Directory Not Found
* **Symptom:** The engine falls back to default settings or throws a config file missing exception.
* **Resolution:** Explicitly pass the custom configuration directory flag:
  ```bash
  aq ingest --source openaq --config-dir ./configs
  ```
  
## 3. Logging and Diagnostics

To diagnose unexpected pipeline behavior, always run commands with verbose logging enabled:

```bash
aq ingest --source openaq --log-level DEBUG
```
Review log output files located locally at:
- `./data/logs/aq_engine.log` (Detailed debug records)
- `./data/logs/aq_engine_error.log` (Error traces)
