# API Usage Guide

Complete guide to using the Air Quality Intelligence Platform REST API.

## Table of Contents

- [Getting Started](#getting-started)
- [Authentication](#authentication)
- [Base URL](#base-url)
- [Response Format](#response-format)
- [Endpoints](#endpoints)
- [Error Handling](#error-handling)
- [Rate Limiting](#rate-limiting)
- [Code Examples](#code-examples)

## Getting Started

The Air Quality Intelligence Platform provides a RESTful API for accessing real-time and historical air quality data, forecasts, and anomaly detection results.

### Prerequisites

- API is available when the platform is running
- Default port: 8000
- Interactive documentation available at `/docs`

### Quick Start

```bash
# Check API health
curl http://localhost:8000/health

# Get current observations
curl http://localhost:8000/observations/current?location_id=kolkata

# View interactive docs
open http://localhost:8000/docs
```

## Authentication

Currently the API does not require authentication for local deployments. For production deployments, implement authentication via:
- API keys (recommended)
- OAuth 2.0
- JWT tokens

## Base URL

**Local Development:**
```
http://localhost:8000
```

**Production:**
```
https://your-domain.com
```

## Response Format

Responses use endpoint-specific JSON objects. The examples below show the exact top-level shape returned by each endpoint.
```

### Error Response

```json
{
  "error": "Error message",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-09-27T10:30:00Z"
}
```

## Endpoints

### Health Check

Check API and service health status.

**Endpoint:** `GET /health`

**Response:**
```json
{
  "version": "0.1.0",
  "timestamp": "2026-09-27T10:30:00Z",
  "status": "healthy",
  "database": "ok",
  "models": "ok",
  "startup_time": "2026-09-27T09:00:00Z"
}
```

**Status Values:**
- `healthy`: All services operational
- `degraded`: Some services unavailable

### Current Observations

Get the latest air quality observations for a location.

**Endpoint:** `GET /observations/current`

**Parameters:**
- `location_id` (required): Location identifier (e.g., "kolkata")

**Example Request:**
```bash
curl "http://localhost:8000/observations/current?location_id=kolkata"
```

**Example Response:**
```json
{
  "location_id": "kolkata",
  "observation_time": "2026-09-27T10:00:00Z",
  "pollutants": [
    {
      "pollutant": "PM2.5",
      "value": 75.2,
      "unit": "µg/m³",
      "timestamp": "2026-09-27T10:00:00Z",
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
    "timestamp": "2026-09-27T10:00:00Z"
  },
  "data_freshness": {
    "age_minutes": 5,
    "status": "FRESH"
  }
}
```

### Historical Observations

Retrieve historical air quality data for a date range.

**Endpoint:** `GET /observations/history`

**Parameters:**
- `location_id` (required): Location identifier
- `start_date` (required): Start date (ISO 8601 format)
- `end_date` (required): End date (ISO 8601 format)
- `pollutant` (optional): Filter by pollutant code (e.g., "pm25")

**Example Request:**
```bash
curl "http://localhost:8000/observations/history?location_id=kolkata&start_date=2026-09-20T00:00:00Z&end_date=2026-09-27T00:00:00Z&pollutant=pm25"
```

**Example Response:**
```json
{
  "location_id": "kolkata",
  "pollutant": "pm25",
  "start_date": "2026-09-20T00:00:00Z",
  "end_date": "2026-09-27T00:00:00Z",
  "observations": [
    {
      "timestamp": "2026-09-20T00:00:00Z",
      "value": 68.5,
      "unit": "µg/m³",
      "quality_flag": "VALID",
      "anomaly_severity": "NORMAL"
    }
  ],
  "total_count": 168,
  "statistics": {
    "mean": 62.3,
    "median": 58.0,
    "min": 28.5,
    "max": 125.0,
    "std_dev": 18.2
  }
}
```

### Anomalies

Get detected anomalies for a location and time period.

**Endpoint:** `GET /observations/anomalies`

**Parameters:**
- `location_id` (required): Location identifier
- `start_date` (optional): Start date filter
- `end_date` (optional): End date filter
- `severity` (optional): Filter by severity (MEDIUM, HIGH, EXTREME)
- `pollutant` (optional): Filter by pollutant

**Example Request:**
```bash
curl "http://localhost:8000/observations/anomalies?location_id=kolkata&severity=HIGH"
```

**Example Response:**
```json
{
  "location_id": "kolkata",
  "anomalies": [
    {
      "detected_at": "2026-09-27T08:00:00Z",
      "pollutant": "pm25",
      "value": 145.8,
      "baseline_median": 55.0,
      "baseline_p95": 80.0,
      "anomaly_score": 4.5,
      "severity": "HIGH",
      "z_score": 5.2,
      "deviation_pct": 165.1
    }
  ],
  "total_count": 12,
  "severity_breakdown": {
    "MEDIUM": 5,
    "HIGH": 6,
    "EXTREME": 1
  }
}
```

### Predictions

Get PM2.5 forecasts for multiple time horizons.

**Endpoint:** `GET /predictions/{location_id}`

**Parameters:**
- `location_id` (required): Location identifier (path parameter)

**Example Request:**
```bash
curl "http://localhost:8000/predictions/kolkata"
```

**Example Response:**
```json
{
  "location_id": "kolkata",
  "predictions": [
    {
      "horizon_minutes": 60,
      "predicted_pm25": 50.0,
      "lower_bound": 45.0,
      "upper_bound": 55.0,
      "confidence": 0.85
    },
    {
      "horizon_minutes": 180,
      "predicted_pm25": 52.0,
      "lower_bound": 46.0,
      "upper_bound": 58.0,
      "confidence": 0.75
    },
    {
      "horizon_minutes": 360,
      "predicted_pm25": 54.0,
      "lower_bound": 47.0,
      "upper_bound": 61.0,
      "confidence": 0.65
    }
  ],
  "generated_at": "2026-09-27T10:30:00Z"
}
```

## Error Handling

### HTTP Status Codes

- `200 OK`: Request succeeded
- `400 Bad Request`: Invalid parameters
- `404 Not Found`: Resource not found
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Server error
- `503 Service Unavailable`: Service temporarily unavailable

### Error Response Structure

```json
{
  "error": "Validation error: start_date must be before end_date",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-09-27T10:30:00Z"
}
```

### Common Errors

**Invalid Date Range:**
```json
{
  "error": "start_date must be before end_date"
}
```

**Missing Required Parameter:**
```json
{
  "error": "location_id cannot be empty"
}
```

**Resource Not Found:**
```json
{
  "error": "Location 'invalid' not found"
}
```

## Rate Limiting

The API implements rate limiting to ensure fair usage and system stability.

### Limits

- **Default:** 100 requests per minute per IP address
- Rate limit headers included in all responses

### Rate Limit Headers

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
```

### Rate Limit Exceeded Response

**Status:** 429 Too Many Requests

```json
{
  "error": "Rate limit exceeded. Maximum 100 requests per minute.",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-09-27T10:30:00Z"
}
```

**Headers:**
```
Retry-After: 60
```

## Code Examples

### Python

```python
import requests
from datetime import datetime, timedelta

# Base URL
BASE_URL = "http://localhost:8000"

# Get current observations
def get_current_observations(location_id):
    response = requests.get(
        f"{BASE_URL}/observations/current",
        params={"location_id": location_id}
    )
    response.raise_for_status()
    return response.json()

# Get historical data
def get_history(location_id, days=7):
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    response = requests.get(
        f"{BASE_URL}/observations/history",
        params={
            "location_id": location_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "pollutant": "pm25"
        }
    )
    response.raise_for_status()
    return response.json()

# Get predictions
def get_predictions(location_id):
    response = requests.get(f"{BASE_URL}/predictions/{location_id}")
    response.raise_for_status()
    return response.json()

# Example usage
if __name__ == "__main__":
    location = "kolkata"
    
    # Current data
    current = get_current_observations(location)
    print(f"Current PM2.5: {current['pollutants'][0]['value']} µg/m³")
    
    # Historical data
    history = get_history(location, days=7)
    print(f"7-day average: {history['statistics']['mean']:.1f} µg/m³")
    
    # Predictions
    predictions = get_predictions(location)
    print(f"1-hour forecast: {predictions['predictions'][0]['predicted_pm25']:.1f} µg/m³")
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');

const BASE_URL = 'http://localhost:8000';

// Get current observations
async function getCurrentObservations(locationId) {
  const response = await axios.get(`${BASE_URL}/observations/current`, {
    params: { location_id: locationId }
  });
  return response.data;
}

// Get historical data
async function getHistory(locationId, days = 7) {
  const endDate = new Date();
  const startDate = new Date(endDate - days * 24 * 60 * 60 * 1000);
  
  const response = await axios.get(`${BASE_URL}/observations/history`, {
    params: {
      location_id: locationId,
      start_date: startDate.toISOString(),
      end_date: endDate.toISOString(),
      pollutant: 'pm25'
    }
  });
  return response.data;
}

// Get predictions
async function getPredictions(locationId) {
  const response = await axios.get(`${BASE_URL}/predictions/${locationId}`);
  return response.data;
}

// Example usage
async function main() {
  const location = 'kolkata';
  
  try {
    // Current data
    const current = await getCurrentObservations(location);
    console.log(`Current PM2.5: ${current.pollutants[0].value} µg/m³`);
    
    // Historical data
    const history = await getHistory(location, 7);
    console.log(`7-day average: ${history.statistics.mean.toFixed(1)} µg/m³`);
    
    // Predictions
    const predictions = await getPredictions(location);
    console.log(`1-hour forecast: ${predictions.predictions[0].predicted_pm25.toFixed(1)} µg/m³`);
  } catch (error) {
    console.error('API Error:', error.response?.data || error.message);
  }
}

main();
```

### cURL

```bash
# Get current observations
curl "http://localhost:8000/observations/current?location_id=kolkata"

# Get 7-day history
START_DATE=$(date -u -d '7 days ago' '+%Y-%m-%dT%H:%M:%SZ')
END_DATE=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
curl "http://localhost:8000/observations/history?location_id=kolkata&start_date=${START_DATE}&end_date=${END_DATE}&pollutant=pm25"

# Get predictions
curl "http://localhost:8000/predictions/kolkata"

# Get anomalies
curl "http://localhost:8000/observations/anomalies?location_id=kolkata&severity=HIGH"

# Check API health
curl "http://localhost:8000/health"
```

## Best Practices

### 1. Handle Rate Limits

Always check rate limit headers and implement exponential backoff:

```python
import time

def make_request_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        response = requests.get(url)
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            time.sleep(retry_after)
            continue
            
        return response
    
    raise Exception("Max retries exceeded")
```

### 2. Use Request IDs for Debugging

Include request IDs when reporting issues:

```python
response = requests.get(url)
request_id = response.headers.get('X-Request-ID')
print(f"Request ID: {request_id}")
```

### 3. Validate Date Ranges

Ensure start_date is before end_date:

```python
from datetime import datetime

def validate_date_range(start, end):
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    
    if start_dt >= end_dt:
        raise ValueError("start_date must be before end_date")
```

### 4. Cache Responses

Cache historical data to reduce API calls:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_history(location_id, start_date, end_date):
    return get_history(location_id, start_date, end_date)
```

## Support

For issues or questions:
- Check interactive docs: http://localhost:8000/docs
- Review error messages and request IDs
- Consult system logs for detailed diagnostics

## Related Documentation

- [System Architecture](01-system-architecture.md)
- [API Specification](05-api-specification.md)
- [Deployment Guide](07-deployment-guide.md)
