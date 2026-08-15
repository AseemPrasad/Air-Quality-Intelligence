# Air Quality Intelligence Platform: API Specification

## Base URL

```
http://localhost:8000/api
```

## Authentication & Rate Limiting

- **Authentication:** None (internal platform)
- **Rate Limiting:** 100 requests/minute per IP
- **Retry:** 429 responses include `Retry-After` header

## Core Endpoints

### 1. GET /locations

**List all monitoring locations**

#### Request
```bash
curl http://localhost:8000/api/locations
```

#### Response (200 OK)
```json
{
  "locations": [
    {
      "location_id": "kolkata_001",
      "name": "Kolkata Center",
      "city": "Kolkata",
      "country": "India",
      "latitude": 22.5726,
      "longitude": 88.3639,
      "timezone": "Asia/Kolkata",
      "active_stations": 3,
      "last_update": "2026-08-15T10:30:00Z"
    },
    {
      "location_id": "delhi_001",
      "name": "Delhi Central",
      "city": "Delhi",
      "country": "India",
      "latitude": 28.7041,
      "longitude": 77.1025,
      "timezone": "Asia/Kolkata",
      "active_stations": 5,
      "last_update": "2026-08-15T10:25:00Z"
    }
  ]
}
```

### 2. GET /locations/{location_id}/current

**Get current observations for a location**

#### Request
```bash
curl http://localhost:8000/api/locations/kolkata_001/current
```

#### Response (200 OK)
```json
{
  "location_id": "kolkata_001",
  "current_time": "2026-08-15T10:30:00Z",
  "pollutants": [
    {
      "pollutant": "PM2.5",
      "value": 65.5,
      "unit": "µg/m³",
      "timestamp": "2026-08-15T10:00:00Z",
      "baseline_median": 55.0,
      "baseline_p95": 80.0,
      "anomaly_severity": "HIGH",
      "anomaly_score": 3.2,
      "quality_flag": "VALID"
    }
  ],
  "weather": {
    "temperature_c": 32.5,
    "humidity_pct": 75,
    "wind_speed_kmh": 12.0,
    "wind_direction_deg": 230.0,
    "timestamp": "2026-08-15T10:00:00Z"
  },
  "freshness": {
    "data_age_minutes": 30,
    "expected_interval_minutes": 60,
    "status": "fresh"
  }
}
```

### 3. GET /locations/{location_id}/history

**Get historical time series for a location**

#### Request Parameters
- `start_date` (required): ISO 8601 date (e.g., `2026-08-01`)
- `end_date` (required): ISO 8601 date (e.g., `2026-08-15`)
- `pollutant` (optional): Pollutant name, default `PM2.5`
- `grain` (optional): `hourly` or `daily`, default `hourly`

#### Request
```bash
curl "http://localhost:8000/api/locations/kolkata_001/history?start_date=2026-08-14&end_date=2026-08-15&grain=hourly"
```

#### Response (200 OK)
```json
{
  "location_id": "kolkata_001",
  "pollutant": "PM2.5",
  "grain": "hourly",
  "start_date": "2026-08-14",
  "end_date": "2026-08-15",
  "data": [
    {
      "hour_start": "2026-08-14T00:00:00Z",
      "mean_value": 58.2,
      "median_value": 57.5,
      "min_value": 42.1,
      "max_value": 75.3,
      "observation_count": 12,
      "coverage_pct": 100.0,
      "baseline_median": 55.0
    }
  ]
}
```

### 4. GET /locations/{location_id}/forecast

**Get multi-horizon forecasts**

#### Request Parameters
- `horizon` (optional): Comma-separated horizons (1h, 3h, 6h), default `1h,3h,6h`

#### Request
```bash
curl "http://localhost:8000/api/locations/kolkata_001/forecast?horizon=1h,3h,6h"
```

#### Response (200 OK)
```json
{
  "location_id": "kolkata_001",
  "generated_at": "2026-08-15T10:30:00Z",
  "forecasts": [
    {
      "horizon_minutes": 60,
      "target_time": "2026-08-15T11:30:00Z",
      "predicted_pm25": 62.0,
      "lower_bound": 55.0,
      "upper_bound": 70.0,
      "confidence": 0.85,
      "model_version": "2026-08-15_hgb"
    },
    {
      "horizon_minutes": 180,
      "target_time": "2026-08-15T13:30:00Z",
      "predicted_pm25": 64.0,
      "lower_bound": 54.0,
      "upper_bound": 75.0,
      "confidence": 0.75,
      "model_version": "2026-08-15_hgb"
    },
    {
      "horizon_minutes": 360,
      "target_time": "2026-08-15T16:30:00Z",
      "predicted_pm25": 66.0,
      "lower_bound": 55.0,
      "upper_bound": 78.0,
      "confidence": 0.65,
      "model_version": "2026-08-15_hgb"
    }
  ]
}
```

### 5. GET /locations/{location_id}/events

**Get pollution events**

#### Request Parameters
- `start_date` (required): ISO 8601 timestamp
- `end_date` (required): ISO 8601 timestamp
- `pollutant` (optional): Pollutant name, default `PM2.5`

#### Request
```bash
curl "http://localhost:8000/api/locations/kolkata_001/events?start_date=2026-08-14T00:00:00Z&end_date=2026-08-15T23:59:59Z"
```

#### Response (200 OK)
```json
{
  "location_id": "kolkata_001",
  "events": [
    {
      "event_id": "evt_20260815_001",
      "pollutant": "PM2.5",
      "start_time": "2026-08-14T22:00:00Z",
      "end_time": "2026-08-15T06:00:00Z",
      "duration_hours": 8,
      "peak_value": 125.3,
      "mean_value": 98.5,
      "peak_anomaly_score": 4.8,
      "severity": "SEVERE",
      "baseline_median": 55.0,
      "weather": {
        "mean_temperature_c": 28.5,
        "mean_humidity_pct": 82,
        "mean_wind_speed_kmh": 3.5
      }
    }
  ]
}
```

### 6. GET /locations/{location_id}/baseline

**Get historical baseline statistics**

#### Request Parameters
- `pollutant` (optional): Pollutant name, default `PM2.5`
- `hour` (optional): Hour 0-23, default current hour
- `month` (optional): Month 1-12, default current month

#### Request
```bash
curl "http://localhost:8000/api/locations/kolkata_001/baseline?month=8&hour=14"
```

#### Response (200 OK)
```json
{
  "location_id": "kolkata_001",
  "pollutant": "PM2.5",
  "month": 8,
  "hour_of_day": 14,
  "observation_count": 62,
  "median": 55.0,
  "mad": 8.5,
  "p50": 55.0,
  "p75": 62.1,
  "p90": 71.3,
  "p95": 78.5,
  "p99": 92.1
}
```

### 7. GET /system/health

**System health status**

#### Response (200 OK)
```json
{
  "system_status": "healthy",
  "timestamp": "2026-08-15T10:30:00Z",
  "components": {
    "database": {
      "status": "ok",
      "latency_ms": 5,
      "connected": true
    },
    "ingestion": {
      "status": "ok",
      "last_openaq_run": "2026-08-15T10:25:00Z",
      "last_weather_run": "2026-08-15T10:26:00Z",
      "openaq_freshness_minutes": 5,
      "weather_freshness_minutes": 4
    },
    "data_quality": {
      "status": "ok",
      "total_records_last_24h": 50000,
      "rejected_records_last_24h": 125,
      "rejection_rate_pct": 0.25,
      "coverage_pct": 96.5
    },
    "ml_models": {
      "status": "ok",
      "production_model": "2026-08-15_hgb",
      "model_mae": 12.3,
      "model_age_hours": 6
    }
  }
}
```

### 8. GET /system/quality

**Data quality report**

#### Response (200 OK)
```json
{
  "report_time": "2026-08-15T10:30:00Z",
  "summary": {
    "total_records": 50000,
    "valid_records": 49875,
    "suspicious_records": 100,
    "invalid_records": 25,
    "duplicate_records": 50
  },
  "by_source": [
    {
      "source": "openaq",
      "total": 25000,
      "valid": 24950,
      "suspicious": 40,
      "invalid": 10
    },
    {
      "source": "open_meteo",
      "total": 25000,
      "valid": 24925,
      "suspicious": 60,
      "invalid": 15
    }
  ],
  "by_location": [
    {
      "location_id": "kolkata_001",
      "total": 5000,
      "valid_pct": 99.8,
      "coverage_pct": 100.0
    }
  ],
  "by_station_health": [
    {
      "station_id": "stn_001",
      "health_score": 95,
      "status": "healthy"
    },
    {
      "station_id": "stn_003",
      "health_score": 45,
      "status": "offline"
    }
  ]
}
```

## Error Responses

### 400 Bad Request
```json
{
  "error": "Invalid date range",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-08-15T10:30:00Z"
}
```

**Common cases:**
- Invalid date format
- end_date < start_date
- Invalid query parameters

### 404 Not Found
```json
{
  "error": "Location kolkata_999 not found",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-08-15T10:30:00Z"
}
```

### 429 Too Many Requests
```json
{
  "error": "Rate limit exceeded",
  "retry_after_seconds": 60,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-08-15T10:30:00Z"
}
```

### 500 Internal Server Error
```json
{
  "error": "Internal server error",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-08-15T10:30:00Z"
}
```

## Response Headers

All responses include:
- `X-Request-ID`: Unique request identifier for tracing
- `Content-Type`: `application/json`
- `Cache-Control`: `no-cache` (data is live)

## Client Examples

### Python
```python
import requests

response = requests.get(
    "http://localhost:8000/api/locations/kolkata_001/forecast",
    params={"horizon": "1h,3h"}
)
forecast = response.json()
print(f"Generated: {forecast['generated_at']}")
for pred in forecast['forecasts']:
    print(f"{pred['horizon_minutes']}h: {pred['predicted_pm25']:.1f} µg/m³")
```

### JavaScript/TypeScript
```typescript
async function getForecast(locationId: string) {
  const response = await fetch(
    `/api/locations/${locationId}/forecast?horizon=1h,3h,6h`
  );
  const data = await response.json();
  return data.forecasts;
}
```

### cURL
```bash
# Get current observations
curl -H "Accept: application/json" \
  http://localhost:8000/api/locations/kolkata_001/current

# Get forecast with custom horizons
curl -H "Accept: application/json" \
  "http://localhost:8000/api/locations/kolkata_001/forecast?horizon=1h,3h"
```

## Performance Targets

| Endpoint | Target | Status |
|----------|--------|--------|
| /locations | < 100 ms | ✅ |
| /current | < 200 ms | ✅ |
| /history | < 500 ms | ✅ |
| /forecast | < 500 ms | ✅ |
| /events | < 500 ms | ✅ |
| /baseline | < 200 ms | ✅ |
| /system/health | < 200 ms | ✅ |
| /system/quality | < 300 ms | ✅ |

---

**Next:** See [Deployment Guide](07-deployment-guide.md) for setup instructions.
