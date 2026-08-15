# CI/CD GitHub Actions Workflows

## Overview

Complete automated CI/CD pipeline for Air Quality Intelligence Platform with four workflows covering code quality, data contracts, performance, and Docker builds.

## Workflow Summary

| Workflow | Trigger | Duration | Purpose |
|----------|---------|----------|---------|
| **CI** | Push to main, PR | 5-30 min | Lint, type check, tests, coverage |
| **Data Contract** | Code changes | 10 min | Validate schemas and data rules |
| **Performance** | Weekly (Sunday) | 60 min | Benchmark testing, regression detection |
| **Docker Build** | Git tags (v*) | 30 min | Build and publish Docker images |

---

## 1. CI Workflow (`.github/workflows/ci.yml`)

### Trigger
- **Push to main:** Automatically runs on every merge
- **Pull Request:** Runs on every PR to prevent broken code merge

### Steps (Sequential, ~5-30 minutes)

```
1. Checkout code
2. Setup Python 3.12
3. Install dependencies
4. Lint with Ruff (2 min)
   └─ `ruff check src tests`
5. Type check with mypy (3 min)
   └─ `mypy src`
6. Unit tests (5 min)
   └─ `pytest tests/unit`
7. Integration tests (5 min)
   └─ `pytest tests/integration`
8. Coverage report (3 min)
   └─ `pytest --cov=src --cov-fail-under=80`
9. Build Docker images (5 min)
   └─ `docker-compose build`
10. Generate summary
11. Report status
```

### Quality Gates

```yaml
Checks Required for Merge:
  ✓ Lint (Ruff)         - No violations
  ✓ Type Check (mypy)   - No type errors
  ✓ Unit Tests          - All pass
  ✓ Coverage            - >= 80%
  ✓ Docker Build        - No errors
```

### Configuration

```yaml
timeout-minutes: 30
python-version: "3.12"
cache: pip dependencies
```

### Artifacts
- **Coverage Report:** Uploaded to CodeCov (if configured)
- **Summary:** Posted to workflow summary

### Example Output

```
✅ CI Summary
├─ Ruff Lint:              success
├─ MyPy Type Check:        success
├─ Unit Tests:             success
├─ Integration Tests:       success
├─ Coverage (80% min):     success (coverage: 95%)
└─ Docker Build:           success
```

---

## 2. Data Contract Validation (`.github/workflows/data-contract-check.yml`)

### Trigger
- **Push to main/PR** when these files change:
  - `src/aq_engine/quality/contracts.py`
  - `src/aq_engine/quality/rules.py`
  - `tests/unit/test_data_contracts.py`
  - `pyproject.toml`

### Purpose
Prevent schema changes that break downstream consumers.

### Steps (~10 minutes)

```
1. Checkout code
2. Setup Python 3.12
3. Install dependencies
4. Validate Pydantic schemas
   └─ Import all contract models
   └─ Instantiate with test data
   └─ Verify no validation errors
5. Run contract tests
   └─ `pytest tests/unit/test_quality_complete.py`
6. Validate data integrity rules
   └─ Import all validation rule classes
   └─ Instantiate each rule
   └─ Verify configuration
7. Generate summary
```

### Validation Includes

```python
# Schema Validation
✓ RawAirQualityRecord
✓ RawWeatherRecord
✓ HourlyFact
✓ Baseline
✓ Anomaly
✓ PollutionEvent

# Validation Rules
✓ AQStructuralValidation
✓ AQSemanticValidation
✓ AQTemporalValidation
✓ AQOutlierValidation
✓ AQStaleValidation
✓ WeatherStructuralValidation
✓ WeatherSemanticValidation
✓ WeatherTemporalValidation
```

### Quality Gates

```yaml
Checks Required for Merge:
  ✓ Pydantic Schemas      - All instantiate
  ✓ Contract Tests        - All pass
  ✓ Integrity Rules       - All load
```

---

## 3. Performance Workflow (`.github/workflows/performance.yml`)

### Trigger
- **Weekly:** Sunday at 00:00 UTC (automated)
- **Manual:** Can be triggered via workflow dispatch

### Purpose
Detect performance regressions before they reach production.

### Steps (~60 minutes)

```
1. Checkout code
2. Setup Python 3.12
3. Install dependencies
4. Run performance benchmarks
   └─ Ingestion tests (OpenAQ, Weather)
   └─ ML tests (Training, Features, Inference)
   └─ API tests (Endpoints, Concurrent load)
5. Analyze for regressions
   └─ Threshold: 20% slowdown = alert
6. Generate performance report
7. Upload artifacts (JSON, histograms)
8. Comment results on PR (if applicable)
```

### Benchmark Targets

```
Ingestion Performance:
  ├─ OpenAQ:   10k records < 2 min
  └─ Weather:  5k records < 2 min

ML Performance:
  ├─ Training:  100k samples < 2 min
  ├─ Features:  10k features < 30 sec
  └─ Inference: Multi-horizon < 1 sec

API Performance:
  ├─ /locations:  < 100 ms
  ├─ /current:    < 200 ms
  ├─ /forecast:   < 500 ms
  └─ Concurrent:  100 req P95 < 1 sec
```

### Regression Detection

```
Regression Threshold: 20% slowdown
├─ < 20% slower:  ✅ OK
├─ 20-50% slower: ⚠️  WARNING
└─ > 50% slower:  ❌ ALERT
```

### Artifacts
- `benchmark_results.json` — Full benchmark data
- `benchmark_histogram/` — Visual comparisons
- **Retention:** 30 days

---

## 4. Docker Build & Push (`.github/workflows/docker-build.yml`)

### Trigger
- **Git Tag:** When version tag pushed (e.g., `v0.1.0`)
- **Manual:** Via workflow dispatch with custom tag

### Purpose
Build and distribute optimized Docker images.

### Steps (~30 minutes)

```
1. Checkout code
2. Setup Docker Buildx
3. Generate image tags (version + latest)
4. Build API image
   └─ docker/Dockerfile.api
   └─ Multi-stage, ~400MB
5. Build Dashboard image
   └─ docker/Dockerfile.dashboard
   └─ Multi-stage, ~450MB
6. Build Worker image
   └─ docker/Dockerfile.worker
   └─ Multi-stage, ~500MB
7. Verify images
   └─ Check sizes
   └─ Verify non-root user
8. Generate build report
9. Upload images as artifacts
10. Create GitHub release (if tag)
```

### Image Tags

```bash
# For tag v0.1.0
aq-api:0.1.0
aq-api:latest

aq-dashboard:0.1.0
aq-dashboard:latest

aq-worker:0.1.0
aq-worker:latest
```

### Build Configuration

```yaml
Cache:           GitHub Actions cache
Buildx:          Multi-platform builds
Compression:     Enabled
Labels:          Version, timestamp, description
```

### Release Notes

Automatically generated and added to GitHub Release.

---

## Workflow Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                       Developer Push                            │
└────────────┬────────────────────────────────────────────────────┘
             │
             ├─→ Push to main
             │   └─→ Trigger: CI + Data Contract
             │       ├─ Lint, Type Check, Tests (5-30 min)
             │       ├─ Data Contract Validation (10 min)
             │       └─ Report: Summary to workflow
             │
             ├─→ Push with tag (v0.1.0)
             │   └─→ Trigger: Docker Build
             │       ├─ Build 3 Docker images (30 min)
             │       ├─ Upload artifacts
             │       └─ Create GitHub Release
             │
             └─→ Pull Request
                 └─→ Trigger: CI + Data Contract
                     ├─ Same checks as main push
                     ├─ Comment: "All checks passed ✅"
                     └─ Block merge if any check fails
```

---

## Status Checks & PR Blocking

### Required Status Checks (Prevent Merge)

```
✓ CI / ci (pull_request)          - All tests must pass
✓ Data Contracts / validation      - All schemas valid
```

### Optional Status Checks (Warning Only)

```
△ Performance / regressions        - Warning if > 20%
△ Docker Build / build             - Optional
```

### Pull Request Comment Example

```markdown
## CI Summary ✅

| Check | Status |
|-------|--------|
| Ruff Lint | ✅ success |
| MyPy Type Check | ✅ success |
| Unit Tests | ✅ success (95 tests) |
| Integration Tests | ✅ success (5 tests) |
| Coverage (80% min) | ✅ success (95% coverage) |
| Docker Build | ✅ success |

**Data Contracts:** ✅ All 6 models validated

**Performance:** 
- Previous run: baseline
- Current run: No regressions detected

**Ready to merge!**
```

---

## Caching Strategy

### Pip Dependencies

```yaml
cache:
  key: ${{ runner.os }}-pip-${{ hashFiles('**/pyproject.toml') }}
  restore-keys: |
    ${{ runner.os }}-pip-
```

**Effect:** Dependency installation < 30 seconds (vs. 5+ minutes without cache)

### Docker Buildx

```yaml
cache-from: type=gha
cache-to: type=gha,mode=max
```

**Effect:** Subsequent builds < 5 minutes (vs. 15+ minutes without cache)

---

## Artifact Retention

| Artifact | Retention | Purpose |
|----------|-----------|---------|
| Coverage Report | Auto (CodeCov) | Historical tracking |
| Performance Benchmarks | 30 days | Regression analysis |
| Docker Images | 7 days | Build debugging |

---

## Environment Secrets (if pushing to registry)

For Docker registry push, add GitHub Secrets:

```
REGISTRY_USERNAME     - Docker registry username
REGISTRY_PASSWORD     - Docker registry password
REGISTRY_URL          - Docker registry URL
```

Then modify Docker Build workflow:

```yaml
- name: Login to Container Registry
  uses: docker/login-action@v2
  with:
    registry: ${{ secrets.REGISTRY_URL }}
    username: ${{ secrets.REGISTRY_USERNAME }}
    password: ${{ secrets.REGISTRY_PASSWORD }}

- name: Push to Registry
  uses: docker/build-push-action@v4
  with:
    push: true  # Enable push
    tags: ${{ secrets.REGISTRY_URL }}/aq-api:latest
```

---

## Troubleshooting

### Workflow Not Triggering

```bash
# Check workflow is enabled
# Settings → Actions → General → Allow all actions

# Check workflow file syntax
# Use https://github.com/rhysd/actionlint (local validation)
```

### Tests Failing in CI but Passing Locally

```bash
# Run with same Python version as CI
python3.12 -m pytest tests/

# Check for environment-specific issues
docker-compose run --rm api pytest tests/
```

### Performance Regression False Alarm

```bash
# Re-run performance workflow
# If still regressed, investigate:
pytest tests/performance -v --benchmark-histogram

# Compare histogram output
```

### Docker Build Failing

```bash
# Test build locally
docker-compose build api

# Check Dockerfile syntax
docker build -f docker/Dockerfile.api --dry-run .
```

---

## Monitoring & Alerts

### GitHub Actions Dashboard

- **Location:** Actions tab in repository
- **Shows:** All workflows, pass/fail status, execution time
- **History:** Last 90 days retained

### Email Notifications

- **When:** Workflow fails
- **Recipient:** Repository owner + committer
- **Frequency:** Per failure (can be tuned in GitHub settings)

### Branch Protection Rules

```
Settings → Branches → main
├─ Require CI checks to pass
├─ Require Data Contract checks to pass
├─ Require code review (optional)
└─ Require branch to be up to date
```

---

## Performance Optimization

### CI Duration Targets

```
Current:  5-30 min (full run)
Target:   < 15 min
Approach:
  ✓ Parallel lint + type check
  ✓ Cached dependencies
  ✓ Incremental coverage
```

### Docker Build Duration

```
Current:  30 min (3 sequential images)
Target:   < 20 min
Approach:
  ✓ Parallel image builds (buildx)
  ✓ Layer caching
  ✓ Multi-platform builds
```

---

## Example: Complete PR Workflow

```
1. Developer creates PR
   └─ Pushes to feature branch

2. GitHub triggers CI workflow
   ├─ Lint & type check (pass)
   ├─ Unit tests (pass)
   ├─ Integration tests (pass)
   ├─ Coverage check (95%, pass)
   └─ Docker build (pass)

3. Data Contract workflow
   ├─ Schema validation (pass)
   ├─ Contract tests (pass)
   └─ Integrity rules (pass)

4. Results posted to PR
   └─ Comment: "All checks passed ✅"

5. PR ready to merge
   ├─ All status checks green
   ├─ Code review approved
   └─ Branch up to date

6. Merge PR
   └─ Triggers CI on main
       ├─ Final verification
       └─ Deploy to staging (if configured)

7. Create git tag v0.1.0
   └─ Triggers Docker Build
       ├─ Build images
       ├─ Create release
       └─ Publish to registry
```

---

## Related Documentation

- [Deployment Guide](Docker-and-Deployment.md)
- [CLI and Configuration](CLI-and-Configuration.md)
- [System Architecture](01-system-architecture.md)

---

**Last Updated:** 2026-08-16  
**Status:** Production Ready ✅
