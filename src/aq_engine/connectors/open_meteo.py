"""Open-Meteo connector for weather data.

Fetches historical and forecast weather data from Open-Meteo API.
Maps air quality monitoring stations to nearest weather grid points using haversine distance.
No API key required.

API Reference: https://open-meteo.com/en/docs/
"""

import hashlib
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from aq_engine.common import (
    ensure_utc,
    log_operation,
    StructuredLogger,
    IngestionFailed,
    DataContractViolation,
)
from aq_engine.connectors.base import BaseConnector
from aq_engine.connectors.models import (
    ConnectorConfig,
    ParsedRecord,
    SourceResponse,
    IngestionRunMetadata,
)


logger = logging.getLogger(__name__)
slog = StructuredLogger(__name__)


class OpenMeteoConnector(BaseConnector):
    """Connector for Open-Meteo weather data.

    Fetches hourly weather observations (temperature, humidity, wind, pressure,
    precipitation, cloud cover) for specified locations. Maps air quality stations
    to nearest weather grid points using haversine distance.

    No API key required. Free service with generous rate limits.

    Example:
        >>> config = ConnectorConfig(
        ...     source_name="open_meteo",
        ...     source_type="weather",
        ...     base_url="https://api.open-meteo.com/v1",
        ...     timeout_seconds=30
        ... )
        >>> connector = OpenMeteoConnector(config)
        >>> # Map OpenAQ stations to weather grid points
        >>> connector.add_location_mapping(station_id="123", latitude=22.5726, longitude=88.3639)
        >>> # Ingest weather for all mapped locations
        >>> run_id, metadata = connector.ingest(lookback_hours=6)
    """

    # Weather parameter codes from Open-Meteo API
    WEATHER_PARAMS = [
        "temperature_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "pressure_msl",
        "precipitation",
        "cloud_cover",
    ]

    # Validation ranges for weather parameters
    VALIDATION_RANGES = {
        "temperature_c": (-60.0, 60.0),      # Kolkata reasonable range
        "humidity_pct": (0.0, 100.0),        # Percentage
        "wind_speed_kmh": (0.0, 200.0),      # Max reasonable wind
        "wind_direction_deg": (0.0, 360.0),  # Compass degrees
        "pressure_hpa": (900.0, 1100.0),     # Barometric pressure
        "precipitation_mm": (0.0, 1000.0),   # Max rain in hour
        "cloud_cover_pct": (0.0, 100.0),     # Percentage
    }

    def __init__(
        self,
        config: ConnectorConfig,
        session: Optional[requests.Session] = None,
    ):
        """Initialize Open-Meteo connector.

        Args:
            config: Connector configuration.
            session: Optional requests.Session for reuse.

        Raises:
            ValueError: If config is invalid.
        """
        super().__init__(config, session=session)
        # Location mapping: station_id → (latitude, longitude)
        self._location_mapping: Dict[str, Tuple[float, float]] = {}

    def add_location_mapping(
        self, station_id: str, latitude: float, longitude: float
    ) -> None:
        """Register a location (station) for weather fetching.

        Args:
            station_id: Unique station identifier (from air quality data).
            latitude: Latitude of station (decimal degrees).
            longitude: Longitude of station (decimal degrees).

        Raises:
            ValueError: If coordinates are invalid.
        """
        if not (-90 <= latitude <= 90):
            raise ValueError(f"Invalid latitude: {latitude}")
        if not (-180 <= longitude <= 180):
            raise ValueError(f"Invalid longitude: {longitude}")

        self._location_mapping[str(station_id)] = (latitude, longitude)
        logger.debug(
            f"Added location mapping: {station_id} @ ({latitude:.4f}, {longitude:.4f})"
        )

    def clear_location_mappings(self) -> None:
        """Clear all location mappings."""
        self._location_mapping.clear()
        logger.debug("Cleared all location mappings")

    def fetch(self, start_time: datetime, end_time: datetime) -> SourceResponse:
        """Fetch weather data for all mapped locations.

        Queries Open-Meteo API for each registered location within time range.
        Aggregates results from all locations into single SourceResponse.

        Args:
            start_time: Query window start (UTC).
            end_time: Query window end (UTC).

        Returns:
            SourceResponse with weather data from all locations.

        Raises:
            IngestionFailed: If no locations mapped or API fails.
        """
        start_time = ensure_utc(start_time)
        end_time = ensure_utc(end_time)

        if not self._location_mapping:
            raise IngestionFailed(
                "No locations registered for weather fetching",
                context={"source": self.config.source_name},
            )

        logger.debug(f"Fetching weather for {len(self._location_mapping)} locations")

        all_weather_data = []

        # Fetch weather for each location
        for station_id, (latitude, longitude) in self._location_mapping.items():
            try:
                weather_data = self._fetch_location_weather(
                    station_id, latitude, longitude, start_time, end_time
                )
                all_weather_data.extend(weather_data)
                logger.debug(f"Fetched {len(weather_data)} records for station {station_id}")
            except IngestionFailed as e:
                logger.warning(f"Failed to fetch weather for station {station_id}: {e}")
                # Continue with other locations
                continue

        if not all_weather_data:
            logger.warning("No weather data fetched from any location")

        # Return aggregated response
        response = SourceResponse(
            status_code=200,
            headers={},
            body={
                "results": all_weather_data,
                "meta": {
                    "total": len(all_weather_data),
                    "locations": len(self._location_mapping),
                },
            },
            elapsed_seconds=0.0,
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(f"Fetched {len(all_weather_data)} weather records from Open-Meteo")
        return response

    def _fetch_location_weather(
        self,
        station_id: str,
        latitude: float,
        longitude: float,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Fetch weather for single location from Open-Meteo API.

        Uses historical data endpoint if end_time is in past,
        otherwise uses forecast endpoint.

        Args:
            station_id: Station identifier.
            latitude: Location latitude.
            longitude: Location longitude.
            start_time: Query start time.
            end_time: Query end time.

        Returns:
            List of weather records for location.

        Raises:
            IngestionFailed: On API error.
        """
        now = datetime.now(timezone.utc)

        # Determine which endpoint to use
        if end_time <= now:
            # Historical data
            url = urljoin(self.config.base_url, "/archive")
        else:
            # Forecast data
            url = urljoin(self.config.base_url, "/forecast")

        # Build query parameters
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_time.date().isoformat(),
            "end_date": end_time.date().isoformat(),
            "hourly": ",".join(self.WEATHER_PARAMS),
            "timezone": "UTC",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "pressure_unit": "hpa",
        }

        try:
            logger.debug(
                f"Requesting {url} for station {station_id} "
                f"({latitude:.4f}, {longitude:.4f})"
            )
            response = self._session.get(
                url,
                params=params,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()

            data = response.json()

            # Validate response structure
            if not isinstance(data, dict):
                raise DataContractViolation(
                    f"Expected dict response, got {type(data).__name__}",
                    context={"url": url, "station_id": station_id},
                )

            # Extract hourly data
            hourly_data = data.get("hourly", {})
            if not isinstance(hourly_data, dict):
                raise DataContractViolation(
                    f"Expected 'hourly' to be dict, got {type(hourly_data).__name__}",
                    context={"url": url, "station_id": station_id},
                )

            # Parse hourly records
            records = self._parse_hourly_records(
                station_id, latitude, longitude, hourly_data, data.get("raw_payload_hash")
            )

            return records

        except requests.HTTPError as e:
            status_code = response.status_code
            body = response.text[:500]

            if status_code == 404:
                raise IngestionFailed(
                    f"Location not found (HTTP 404): ({latitude}, {longitude})",
                    context={
                        "url": url,
                        "status_code": status_code,
                        "station_id": station_id,
                    },
                ) from e

            elif status_code in (429, 500, 502, 503, 504):
                raise IngestionFailed(
                    f"Transient error (HTTP {status_code}): {body}",
                    context={
                        "url": url,
                        "status_code": status_code,
                        "station_id": station_id,
                    },
                ) from e

            else:
                raise IngestionFailed(
                    f"HTTP {status_code}: {body}",
                    context={
                        "url": url,
                        "status_code": status_code,
                        "station_id": station_id,
                    },
                ) from e

        except requests.Timeout as e:
            raise IngestionFailed(
                f"Timeout fetching weather for station {station_id}",
                context={"url": url, "station_id": station_id},
            ) from e

        except ValueError as e:
            raise DataContractViolation(
                f"Malformed JSON response: {str(e)}",
                context={"url": url, "station_id": station_id},
            ) from e

    def _parse_hourly_records(
        self,
        station_id: str,
        latitude: float,
        longitude: float,
        hourly_data: Dict[str, Any],
        raw_payload_hash: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Parse hourly weather data into canonical records.

        Args:
            station_id: Station identifier.
            latitude: Station latitude.
            longitude: Station longitude.
            hourly_data: Hourly data dict from API response.
            raw_payload_hash: Hash of raw API response.

        Returns:
            List of canonical weather records.
        """
        records = []

        # Extract time series
        times = hourly_data.get("time", [])
        if not isinstance(times, list) or not times:
            logger.warning(f"No time data for station {station_id}")
            return records

        # Extract parameter series
        temperatures = hourly_data.get("temperature_2m", [])
        humidities = hourly_data.get("relative_humidity_2m", [])
        wind_speeds = hourly_data.get("wind_speed_10m", [])
        wind_directions = hourly_data.get("wind_direction_10m", [])
        pressures = hourly_data.get("pressure_msl", [])
        precipitations = hourly_data.get("precipitation", [])
        cloud_covers = hourly_data.get("cloud_cover", [])

        # Process each hour
        for i, time_str in enumerate(times):
            try:
                # Parse timestamp
                if isinstance(time_str, str):
                    # ISO format: "2026-08-15T12:00"
                    observed_at = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    if observed_at.tzinfo is None:
                        observed_at = observed_at.replace(tzinfo=timezone.utc)
                else:
                    # Unix timestamp (seconds since epoch)
                    observed_at = datetime.fromtimestamp(time_str, tz=timezone.utc)

                observed_at = ensure_utc(observed_at)

                # Extract values (safely, with None handling)
                temperature = temperatures[i] if i < len(temperatures) else None
                humidity = humidities[i] if i < len(humidities) else None
                wind_speed = wind_speeds[i] if i < len(wind_speeds) else None
                wind_direction = wind_directions[i] if i < len(wind_directions) else None
                pressure = pressures[i] if i < len(pressures) else None
                precipitation = precipitations[i] if i < len(precipitations) else None
                cloud_cover = cloud_covers[i] if i < len(cloud_covers) else None

                # Build and validate record
                record = self._build_weather_record(
                    station_id,
                    latitude,
                    longitude,
                    observed_at,
                    temperature,
                    humidity,
                    wind_speed,
                    wind_direction,
                    pressure,
                    precipitation,
                    cloud_cover,
                    raw_payload_hash,
                )

                if record:
                    records.append(record)

            except (ValueError, TypeError) as e:
                logger.warning(
                    f"Skipping malformed record for station {station_id} at {time_str}: {e}"
                )
                continue

        logger.debug(f"Parsed {len(records)} records for station {station_id}")
        return records

    def _build_weather_record(
        self,
        station_id: str,
        latitude: float,
        longitude: float,
        observed_at: datetime,
        temperature: Optional[float],
        humidity: Optional[float],
        wind_speed: Optional[float],
        wind_direction: Optional[float],
        pressure: Optional[float],
        precipitation: Optional[float],
        cloud_cover: Optional[float],
        raw_payload_hash: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Build and validate single weather record.

        Applies validation rules and skips records with null/invalid values.

        Args:
            station_id: Station ID.
            latitude: Station latitude.
            longitude: Station longitude.
            observed_at: Observation timestamp (UTC).
            temperature: Temperature in Celsius.
            humidity: Relative humidity (0-100%).
            wind_speed: Wind speed in km/h.
            wind_direction: Wind direction in degrees (0-360).
            pressure: Barometric pressure in hPa.
            precipitation: Precipitation in mm.
            cloud_cover: Cloud cover (0-100%).
            raw_payload_hash: Hash of raw API response.

        Returns:
            Canonical weather record dict or None if invalid.
        """
        # Check for required fields
        if temperature is None or humidity is None:
            logger.debug(
                f"Skipping record for {station_id} with missing temperature or humidity"
            )
            return None

        # Validate ranges
        if not self._validate_value("temperature_c", temperature):
            return None
        if not self._validate_value("humidity_pct", humidity):
            return None
        if wind_speed is not None and not self._validate_value("wind_speed_kmh", wind_speed):
            return None
        if wind_direction is not None and not self._validate_value(
            "wind_direction_deg", wind_direction
        ):
            return None
        if pressure is not None and not self._validate_value("pressure_hpa", pressure):
            return None
        if precipitation is not None and not self._validate_value(
            "precipitation_mm", precipitation
        ):
            return None
        if cloud_cover is not None and not self._validate_value("cloud_cover_pct", cloud_cover):
            return None

        # Build canonical record
        record = {
            "source": "open_meteo",
            "location_id": station_id,
            "observed_at": observed_at,
            "temperature_c": float(temperature),
            "humidity_pct": float(humidity),
            "wind_speed_kmh": float(wind_speed) if wind_speed is not None else None,
            "wind_direction_deg": float(wind_direction) if wind_direction is not None else None,
            "pressure_hpa": float(pressure) if pressure is not None else None,
            "precipitation_mm": float(precipitation) if precipitation is not None else None,
            "cloud_cover_pct": float(cloud_cover) if cloud_cover is not None else None,
            "ingested_at": datetime.now(timezone.utc),
            "raw_payload_hash": raw_payload_hash,
        }

        return record

    def _validate_value(self, field_name: str, value: Optional[float]) -> bool:
        """Validate weather parameter against expected range.

        Args:
            field_name: Parameter name (key in VALIDATION_RANGES).
            value: Value to validate.

        Returns:
            True if valid, False otherwise.
        """
        if value is None:
            return True  # Null is allowed (optional fields)

        if field_name not in self.VALIDATION_RANGES:
            logger.warning(f"Unknown field for validation: {field_name}")
            return True  # Unknown fields pass through

        min_val, max_val = self.VALIDATION_RANGES[field_name]
        if not (min_val <= value <= max_val):
            logger.debug(f"Value out of range for {field_name}: {value} (expected {min_val}-{max_val})")
            return False

        return True

    def parse(
        self, response: SourceResponse, start_time: datetime, end_time: datetime
    ) -> List[ParsedRecord]:
        """Parse Open-Meteo response into canonical weather records.

        Args:
            response: SourceResponse from fetch().
            start_time: Query window start.
            end_time: Query window end.

        Returns:
            List of canonical ParsedRecord objects.

        Raises:
            DataContractViolation: If response is malformed.
        """
        records = []

        if not isinstance(response.body, dict):
            raise DataContractViolation(
                f"Expected dict response body, got {type(response.body).__name__}"
            )

        weather_records = response.body.get("results", [])
        if not isinstance(weather_records, list):
            raise DataContractViolation(
                f"Expected 'results' to be list, got {type(weather_records).__name__}"
            )

        for weather_record in weather_records:
            try:
                # Compute measurement key for idempotency
                measurement_key = hashlib.sha256(
                    f"open_meteo|{weather_record['location_id']}|{weather_record['observed_at'].isoformat()}".encode()
                ).hexdigest()

                parsed = ParsedRecord(
                    source="open_meteo",
                    record_type="weather",
                    data=weather_record,
                    measurement_key=measurement_key,
                    raw_payload_hash=response.raw_payload_hash or "",
                    ingestion_timestamp=datetime.now(timezone.utc),
                )
                records.append(parsed)

            except (KeyError, TypeError, ValueError) as e:
                logger.warning(
                    f"Skipping malformed weather record: {e}",
                    extra={"record": str(weather_record)[:500]},
                )
                continue

        logger.info(f"Parsed {len(records)} weather records from {len(weather_records)} raw records")
        return records

    def write_raw(
        self, records: List[ParsedRecord], run_id: str
    ) -> Tuple[int, int]:
        """Write parsed records to raw Parquet storage.

        Partitions by date (year/month/day) and location.

        Args:
            records: Canonical records to write.
            run_id: Ingestion run identifier.

        Returns:
            Tuple of (records_written, records_rejected).

        Raises:
            StorageError: On write failure.
        """
        import polars as pl
        from pathlib import Path

        from aq_engine.common import date_partition_path

        if not records:
            logger.info("No records to write")
            return 0, 0

        # Convert to Polars DataFrame
        data = [r.data for r in records]
        df = pl.DataFrame(data)

        # Add run_id for traceability
        df = df.with_columns(pl.lit(run_id).alias("run_id"))

        # Group by date partition and write
        written_count = 0
        rejected_count = 0

        try:
            for partition_value, group_df in df.groupby(
                pl.col("observed_at").dt.date()
            ):
                # Compute partition path
                observed_date = partition_value
                partition_path = date_partition_path(observed_date)

                # Construct full path
                storage_path = Path(f"data/raw/weather/{partition_path}")
                storage_path.mkdir(parents=True, exist_ok=True)

                # Write Parquet (append mode)
                output_file = storage_path / f"records_{run_id[:8]}.parquet"

                group_df.write_parquet(
                    str(output_file),
                    compression="snappy",
                    row_group_size=10000,
                )

                written_count += len(group_df)
                logger.debug(f"Wrote {len(group_df)} records to {output_file}")

            logger.info(f"Wrote {written_count} records to raw storage")
            return written_count, rejected_count

        except Exception as e:
            from aq_engine.common import StorageError

            raise StorageError(
                f"Failed to write records to Parquet: {str(e)}",
                context={"run_id": run_id, "record_count": len(records)},
            ) from e

    def record_run(self, metadata: IngestionRunMetadata, success: bool) -> None:
        """Record ingestion run in PostgreSQL control plane.

        Args:
            metadata: Run metadata.
            success: Whether run succeeded.

        Raises:
            DatabaseError: On database error.
        """
        # TODO: Implement after PostgreSQL integration
        logger.info(
            f"Run {metadata.run_id}: status={metadata.status}, "
            f"written={metadata.records_written}, rejected={metadata.records_rejected}",
            extra={
                "event": "ingestion_run_record",
                "run_id": metadata.run_id,
                "status": metadata.status,
                "success": success,
                "records_written": metadata.records_written,
                "records_rejected": metadata.records_rejected,
            },
        )

        if success:
            logger.debug(f"Watermark would be advanced for run {metadata.run_id}")
        else:
            logger.warning(f"Watermark NOT advanced for failed run {metadata.run_id}")


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points on Earth.

    Uses haversine formula for accurate distance over Earth's surface.

    Args:
        lat1: First point latitude (decimal degrees).
        lon1: First point longitude (decimal degrees).
        lat2: Second point latitude (decimal degrees).
        lon2: Second point longitude (decimal degrees).

    Returns:
        Distance in kilometers.

    Example:
        >>> # Distance from Kolkata center to a point 100km south
        >>> dist = haversine_distance(22.5726, 88.3639, 22.0, 88.3639)
        >>> print(f"{dist:.1f} km")
    """
    R = 6371.0  # Earth's radius in kilometers

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return R * c
