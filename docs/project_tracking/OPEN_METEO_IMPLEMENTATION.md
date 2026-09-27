# Open-Meteo Connector Implementation

## ✓ COMPLETE (2 Files, 1,318 Lines)

### Files Created

1. **src/aq_engine/connectors/open_meteo.py** (709 lines)
2. **tests/unit/test_open_meteo_connector.py** (609 lines)

---

## 1. Open-Meteo Connector (open_meteo.py)

### OpenMeteoConnector Class

Extends `BaseConnector` to fetch, parse, and store weather observations from Open-Meteo API.

**Key Features:**
- No API key required (free service)
- Location mapping: Air quality stations → weather grid points
- Haversine distance for nearest point calculation
- Hourly weather data alignment
- Comprehensive validation (temperature, humidity, wind, pressure, etc.)
- Supports both historical and forecast data

#### Constructor

```python
def __init__(
    self,
    config: ConnectorConfig,
    session: Optional[requests.Session] = None
)
```

- `config`: Connector configuration (base_url, timeout, retry, rate_limit)
- `session`: Optional requests.Session for reuse/testing
- `_location_mapping`: Dict of station_id → (latitude, longitude)

#### Location Mapping

##### `add_location_mapping(station_id, latitude, longitude) → None`

Register an air quality station for weather fetching.

**Parameters:**
- `station_id`: Unique identifier (e.g., OpenAQ location ID)
- `latitude`: Location latitude (-90 to +90 degrees)
- `longitude`: Location longitude (-180 to +180 degrees)

**Validation:**
- Raises ValueError if latitude/longitude out of bounds
- Logs mapping at DEBUG level

**Example:**
```python
connector.add_location_mapping("kolkata_center", 22.5726, 88.3639)
connector.add_location_mapping("south_kolkata", 22.45, 88.2)
```

##### `clear_location_mappings() → None`

Remove all registered locations.

#### Public Methods

##### `fetch(start_time, end_time) → SourceResponse`

Fetches weather data for all mapped locations within time range.

**Flow:**
1. Validates that locations are registered
2. For each location:
   - Calls `_fetch_location_weather()`
   - Aggregates results
   - Logs warning on per-location failures (continues with others)
3. Returns SourceResponse with all weather data

**Parameters:**
- `start_time`: Query start time (UTC)
- `end_time`: Query end time (UTC)

**Returns:**
- SourceResponse with:
  - `body["results"]`: List of all weather records from all locations
  - `body["meta"]["total"]`: Total record count
  - `body["meta"]["locations"]`: Number of locations queried

**Error Handling:**
- Raises IngestionFailed if no locations registered
- Logs warning per location if fetch fails
- Continues with other locations (partial results acceptable)

##### `_fetch_location_weather(station_id, latitude, longitude, start_time, end_time) → List[Dict]`

Internal method fetching weather for single location.

**Endpoint Selection:**
```python
if end_time <= now:
    url = "/archive"      # Historical data
else:
    url = "/forecast"     # Forecast data
```

**Query Parameters:**
```python
{
    "latitude": latitude,
    "longitude": longitude,
    "start_date": start_time.date().isoformat(),
    "end_date": end_time.date().isoformat(),
    "hourly": "temperature_2m,relative_humidity_2m,...",  # All params
    "timezone": "UTC",
    "temperature_unit": "celsius",
    "wind_speed_unit": "kmh",
    "precipitation_unit": "mm",
    "pressure_unit": "hpa",
}
```

**Error Handling:**
- HTTP 404: Raise IngestionFailed (location not found)
- HTTP 429/5xx: Raise IngestionFailed (retry in BaseConnector)
- Timeout: Raise IngestionFailed
- Malformed JSON: Raise DataContractViolation

**Returns:**
- List of canonical weather records for location

##### `_parse_hourly_records(station_id, latitude, longitude, hourly_data, raw_payload_hash) → List[Dict]`

Parse hourly time series from API into canonical records.

**Process:**
1. Extract time array
2. Extract parameter arrays (temperature, humidity, wind, etc.)
3. Zip arrays together by hour index
4. Build and validate each record
5. Skip invalid records (logs warning)

**Returns:**
- List of canonical weather record dicts

##### `_build_weather_record(...) → Optional[Dict]`

Build and validate single weather record.

**Validation:**
- Checks required fields (temperature, humidity)
- Validates ranges for all fields
- Skips if null/invalid (logs debug message)

**Canonical Record Schema:**
```python
{
    "source": "open_meteo",
    "location_id": str,                    # Station ID
    "observed_at": datetime,               # UTC
    "temperature_c": float,                # Required
    "humidity_pct": float,                 # Required
    "wind_speed_kmh": float,               # Optional
    "wind_direction_deg": float,           # Optional
    "pressure_hpa": float,                 # Optional
    "precipitation_mm": float,             # Optional
    "cloud_cover_pct": float,              # Optional
    "ingested_at": datetime,               # Now (UTC)
    "raw_payload_hash": str,               # SHA256 of raw response
}
```

**Returns:**
- Record dict if valid
- None if validation fails

##### `_validate_value(field_name, value) → bool`

Validate weather parameter against expected range.

**Validation Ranges:**
```python
{
    "temperature_c": (-60.0, 60.0),       # Kolkata range
    "humidity_pct": (0.0, 100.0),         # Percentage
    "wind_speed_kmh": (0.0, 200.0),       # Max reasonable
    "wind_direction_deg": (0.0, 360.0),   # Compass degrees
    "pressure_hpa": (900.0, 1100.0),      # Barometric
    "precipitation_mm": (0.0, 1000.0),    # Max rain/hour
    "cloud_cover_pct": (0.0, 100.0),      # Percentage
}
```

**Returns:**
- True if valid or None
- False if out of range (logs debug message)

##### `parse(response, start_time, end_time) → List[ParsedRecord]`

Convert Open-Meteo response into canonical weather records.

**Process:**
1. Validates response body is dict
2. Validates "results" key is list
3. For each record:
   - Computes SHA256 measurement_key (idempotency)
   - Creates ParsedRecord
   - Catches and logs malformed records
4. Returns list of ParsedRecord objects

**Returns:**
- List of canonical ParsedRecord objects

##### `write_raw(records, run_id) → Tuple[int, int]`

Write parsed records to raw Parquet storage.

**Storage Layout:**
```
data/raw/weather/
  year=2026/
    month=08/
      day=15/
        records_<run_id_prefix>.parquet
```

**Process:**
1. Convert ParsedRecord list to Polars DataFrame
2. Add run_id column for traceability
3. Group by date partition
4. Write each partition to separate Parquet file (snappy compression)

**Returns:**
- (records_written, records_rejected)

##### `record_run(metadata, success) → None`

Record ingestion run in PostgreSQL control plane.

**Current Implementation:**
- Logs run metadata to structured logger
- Logs warning if success=False (watermark not advanced)

**Future:**
```python
# Update ingestion_run table
# IF success:
#     UPDATE watermark SET last_successful_event_time = ...
# ELSE:
#     DO NOT update watermark
```

### Haversine Distance Function

#### `haversine_distance(lat1, lon1, lat2, lon2) → float`

Calculate great-circle distance between two points on Earth.

**Formula:**
Uses haversine formula for accurate distance over spherical surface.

**Parameters:**
- `lat1`, `lon1`: First point (decimal degrees)
- `lat2`, `lon2`: Second point (decimal degrees)

**Returns:**
- Distance in kilometers

**Example:**
```python
# Kolkata center to a point 100km south
dist = haversine_distance(22.5726, 88.3639, 22.0, 88.3639)
# Returns approximately 63.6 km (1 degree south ≈ 111 km)
```

**Accuracy:**
- Assumes Earth is perfect sphere (R = 6371 km)
- Error < 0.5% for distances up to 10,000 km
- Suitable for location matching (nearest grid point)

---

## 2. Unit Tests (test_open_meteo_connector.py)

### Test Coverage

**7 test classes, 33 test methods, comprehensive coverage:**

#### TestLocationMapping (5 tests)
- `test_add_single_location()` — Add one location
- `test_add_multiple_locations()` — Add multiple locations
- `test_add_location_invalid_latitude()` — Reject invalid latitude
- `test_add_location_invalid_longitude()` — Reject invalid longitude
- `test_clear_location_mappings()` — Clear all mappings

**Also tests:**
- `test_fetch_without_locations_raises_error()` — Fetch requires locations

#### TestHaversineDistance (4 tests)
- `test_haversine_same_point()` — Distance = 0 for same point
- `test_haversine_kolkata_to_north()` — 1° north ≈ 111 km
- `test_haversine_kolkata_to_east()` — 1° east ≈ 92 km (at Kolkata latitude)
- `test_haversine_symmetry()` — Distance is symmetric

#### TestFetchWeather (3 tests)
- `test_fetch_single_location_historical()` — Single location fetch
- `test_fetch_multiple_locations_aggregates()` — Multiple locations combined
- `test_fetch_partial_failure_continues()` — One location fails, others proceed

#### TestParsing (3 tests)
- `test_parse_valid_weather_record()` — Well-formed record parses
- `test_parse_multiple_records()` — Multiple records parsed correctly
- `test_parse_malformed_response()` — Non-dict body raises DataContractViolation

#### TestValidation (12 tests)
- `test_validate_temperature_in_range()` — Valid temperature
- `test_validate_temperature_below_minimum()` — Rejects < -60°C
- `test_validate_temperature_above_maximum()` — Rejects > +60°C
- `test_validate_humidity_in_range()` — Valid humidity
- `test_validate_humidity_above_100()` — Rejects > 100%
- `test_validate_wind_direction_in_range()` — Valid direction
- `test_validate_wind_direction_above_360()` — Rejects > 360°
- `test_validate_pressure_in_range()` — Valid pressure
- `test_validate_null_optional_fields_allowed()` — Wind, precipitation optional
- `test_validate_missing_required_temperature()` — Rejects null temperature
- `test_validate_missing_required_humidity()` — Rejects null humidity

#### TestErrorHandling (4 tests)
- `test_handle_404_not_found()` — Invalid coordinates fail
- `test_handle_500_server_error()` — Server errors trigger retry
- `test_handle_timeout()` — Timeouts trigger retry
- `test_handle_malformed_json()` — Bad JSON raises DataContractViolation

#### TestRecordRun (2 tests)
- `test_record_run_success()` — Success logged
- `test_record_run_failure()` — Failure logged, watermark not advanced

### Test Fixtures

```python
@pytest.fixture
def connector_config() -> ConnectorConfig
    # Valid Open-Meteo connector config

@pytest.fixture
def connector(connector_config) -> OpenMeteoConnector
    # Connector with mocked Session

@pytest.fixture
def connector_with_locations(connector) -> OpenMeteoConnector
    # Pre-configured with 2 locations:
    # - kolkata_center (22.5726, 88.3639)
    # - south_kolkata (22.45, 88.3639)
```

---

## Canonical Weather Record Schema

Weather observation in canonical form:

```python
{
    "source": "open_meteo",                # Source identifier
    "location_id": "123",                  # Station ID (string)
    "observed_at": datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC),
    "temperature_c": 28.5,                 # Required, -60 to +60°C
    "humidity_pct": 65.0,                  # Required, 0-100%
    "wind_speed_kmh": 8.5,                 # Optional, 0-200 km/h
    "wind_direction_deg": 180.0,           # Optional, 0-360°
    "pressure_hpa": 1013.0,                # Optional, 900-1100 hPa
    "precipitation_mm": 0.1,               # Optional, 0-1000 mm
    "cloud_cover_pct": 40.0,               # Optional, 0-100%
    "ingested_at": datetime(2026, 8, 15, 12, 5, 30, tzinfo=UTC),
    "raw_payload_hash": "abc123..."        # SHA256 of raw API response
}
```

**Measurement Key (Idempotency):**
```python
measurement_key = SHA256("open_meteo|123|2026-08-15T12:00:00+00:00")
```
- Ensures duplicate observations are detected
- Used in deduplication layer (M2)

---

## Validation Rules

### Temperature (-60 to +60°C)
- Allows reasonable range for Kolkata
- Kolkata annual: 8–45°C
- Rejects unrealistic extremes

### Humidity (0–100%)
- Percentage range
- Rejects values outside bounds

### Wind Speed (0–200 km/h)
- Reasonable maximum (extreme hurricanes)
- Rejects physically impossible values

### Wind Direction (0–360°)
- Compass degrees
- Rejects values outside full circle

### Pressure (900–1100 hPa)
- Barometric pressure range
- Kolkata typical: 1010–1015 hPa
- Rejects extreme low/high

### Precipitation (0–1000 mm)
- Maximum 1000mm in one hour is extreme
- Rejects physically impossible rainfall

### Cloud Cover (0–100%)
- Percentage range
- Rejects values outside bounds

### Required vs Optional
- **Required:** temperature, humidity
  - Record rejected if either null
- **Optional:** wind, pressure, precipitation, cloud cover
  - Can be null (data missing from API)

---

## Error Handling Flow

### API Response Errors

```
HTTP 2xx Success
  → Process response

HTTP 404 Not Found
  → Raise IngestionFailed (coordinates invalid)
  → Do NOT retry (permanent error)

HTTP 429 Too Many Requests
  → Raise IngestionFailed
  → BaseConnector retries with exponential backoff

HTTP 5xx Server Error
  → Raise IngestionFailed
  → BaseConnector retries with exponential backoff

Timeout
  → Raise IngestionFailed
  → BaseConnector retries with exponential backoff

Malformed JSON
  → Raise DataContractViolation
  → BaseConnector does NOT retry
```

### Per-Location Failure Semantics

When fetching weather for multiple locations:
```python
for station_id, (lat, lon) in location_mapping.items():
    try:
        weather = fetch_location_weather(...)
        results.extend(weather)
    except IngestionFailed:
        logger.warning(f"Failed for {station_id}, continuing")
        # Continue with other locations
        continue

# Return partial results (aggregated from successful locations)
return results
```

---

## Location Mapping Strategy

### Manual Mapping (Current)
```python
# Caller registers stations explicitly
connector.add_location_mapping("station_123", latitude, longitude)
connector.add_location_mapping("station_456", latitude, longitude)
```

### Future: Nearest Grid Point
```python
# TODO: Query OpenAQ for all Kolkata stations
# TODO: For each station, find nearest Open-Meteo grid point
# TODO: Store mapping in PostgreSQL location_weather_grid table

for station in openaq_stations:
    nearest_grid = find_nearest_grid_point(station.lat, station.lon)
    connector.add_location_mapping(station.id, nearest_grid.lat, nearest_grid.lon)
```

**Grid Point Resolution:**
- Open-Meteo provides ~0.1° (11 km) resolution
- Suitable for weather alignment with air quality stations
- Kolkata area: ~4–5 grid points sufficient

---

## Hourly Data Alignment

### Current Implementation
Open-Meteo returns complete hourly time series:
```python
{
    "time": ["2026-08-15T00:00", "2026-08-15T01:00", ...],
    "temperature_2m": [25.0, 24.5, ...],
    "humidity_2m": [70, 72, ...],
    ...
}
```

API guarantees:
- One value per hour
- Aligned to UTC hour boundaries
- No gaps (if data exists)

### Stale/Early Data Handling
Open-Meteo forecast endpoint:
- Real-time updates every 15 minutes
- Historical data available same-day
- Late arrivals: merged by date partition (M2)

---

## Configuration (from configs/sources/open_meteo.yaml)

```yaml
open_meteo:
  name: "Open-Meteo API"
  base_url: "https://api.open-meteo.com/v1"
  timeout_seconds: 30
  
  weather_params:
    - code: "temperature_2m"
    - code: "relative_humidity_2m"
    - code: "wind_speed_10m"
    - code: "wind_direction_10m"
    - code: "pressure_msl"
    - code: "precipitation"
    - code: "cloud_cover"
  
  options:
    timezone: "UTC"
    temperature_unit: "celsius"
    windspeed_unit: "kmh"
    precipitation_unit: "mm"
    pressure_unit: "hpa"
```

---

## Usage Example

```python
from aq_engine.connectors.open_meteo import OpenMeteoConnector
from aq_engine.connectors.models import ConnectorConfig
from datetime import datetime, timezone

# Create config
config = ConnectorConfig(
    source_name="open_meteo",
    source_type="weather",
    base_url="https://api.open-meteo.com/v1",
    timeout_seconds=30
)

# Create connector
connector = OpenMeteoConnector(config)

# Register locations (from OpenAQ stations)
connector.add_location_mapping("kolkata_center", 22.5726, 88.3639)
connector.add_location_mapping("south_kolkata", 22.45, 88.2)
connector.add_location_mapping("north_kolkata", 22.65, 88.3)

# Ingest weather with automatic retry logic
run_id, metadata = connector.ingest(
    start_time=datetime(2026, 8, 15, tzinfo=timezone.utc),
    end_time=datetime(2026, 8, 16, tzinfo=timezone.utc),
    lookback_hours=6
)

# Handle result
if metadata.status == "success":
    print(f"Ingested {metadata.records_written} weather records")
else:
    print(f"Ingestion failed: {metadata.error_message}")

# Test: fetch raw weather
response = connector.fetch(
    datetime(2026, 8, 15, tzinfo=timezone.utc),
    datetime(2026, 8, 16, tzinfo=timezone.utc)
)
print(f"Fetched {response.body['meta']['total']} records from {response.body['meta']['locations']} locations")

# Test: haversine distance
from aq_engine.connectors.open_meteo import haversine_distance
dist = haversine_distance(22.5726, 88.3639, 23.0, 89.0)
print(f"Distance: {dist:.1f} km")
```

---

## Quality Standards ✅

| Standard | Implementation |
|----------|---|
| **Type Hints** | Full coverage on all methods |
| **Docstrings** | Comprehensive with examples |
| **Validation** | All weather parameters validated against ranges |
| **Error Handling** | 5 error types tested, specific exceptions |
| **Logging** | DEBUG, INFO, WARNING levels with context |
| **Location Mapping** | Explicit registration + distance calculation |
| **Hourly Alignment** | UTC timestamps, exact hour boundaries |
| **Required Fields** | Temperature & humidity required, others optional |
| **Null Handling** | Explicit, logs debug messages |
| **Idempotency** | measurement_key = SHA256 of location+timestamp |
| **Testing** | 33 tests covering happy path, validation, errors |

---

## Test Execution

```bash
# Run all Open-Meteo tests
pytest tests/unit/test_open_meteo_connector.py -v

# Run specific test class
pytest tests/unit/test_open_meteo_connector.py::TestValidation -v

# Run with coverage
pytest tests/unit/test_open_meteo_connector.py --cov=src/aq_engine/connectors

# Run specific test
pytest tests/unit/test_open_meteo_connector.py::TestLocationMapping::test_add_single_location -v
```

---

## Next Steps: M2 Quality Layer

Both OpenAQ and Open-Meteo connectors are ready for integration with:
1. **Data Quality Layer** — Deduplication, validation, quarantine
2. **PostgreSQL Control Plane** — Record runs, advance watermarks
3. **Parquet Storage** — Partition by date, compress
4. **Data Correlation** — Match air quality and weather by time/location

After M2 Quality, next is **M3 Analytics** (hourly aggregation, baselines, correlation).

---

## Summary

- ✅ **709 lines** of production-ready connector code
- ✅ **609 lines** of comprehensive unit tests
- ✅ **33 test methods** covering all functionality
- ✅ **Haversine distance** for location matching
- ✅ **Comprehensive validation** for 7 weather parameters
- ✅ **Location mapping** for station-to-grid-point alignment
- ✅ **Hourly data** from Open-Meteo API
- ✅ **Full error handling** with specific exceptions
- ✅ **Watermark-aware** incremental ingestion

Ready for M1 Ingestion integration and M2 Quality layer development.
