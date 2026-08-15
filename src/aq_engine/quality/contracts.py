"""Data contracts (Pydantic schemas) for air quality and weather records.

Defines canonical schemas for raw data validation.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RawAirQualityRecord(BaseModel):
    """Raw air quality observation from OpenAQ.

    Represents a single measurement from an air quality monitoring station.
    Used for validation when writing to Parquet storage.

    Attributes:
        source: Source identifier (e.g., "openaq").
        station_id: Station/location identifier.
        sensor_id: Sensor identifier.
        pollutant: Pollutant code (e.g., "pm25", "pm10", "no2").
        value: Measurement value (float).
        unit: Unit of measurement (e.g., "µg/m³", "ppb").
        observed_at: When observation was made (UTC).
        ingested_at: When data was ingested (UTC).
        raw_payload_hash: SHA256 hash of raw API response.
    """

    source: str = Field(..., description="Source identifier")
    station_id: str = Field(..., description="Station/location ID")
    sensor_id: str = Field(..., description="Sensor ID")
    pollutant: str = Field(..., description="Pollutant code (lowercase)")
    value: float = Field(..., description="Measurement value")
    unit: str = Field(..., description="Unit of measurement")
    observed_at: datetime = Field(..., description="Observation timestamp (UTC)")
    ingested_at: datetime = Field(..., description="Ingestion timestamp (UTC)")
    raw_payload_hash: str = Field(..., description="SHA256 hash of raw payload")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "source": "openaq",
                "station_id": "123",
                "sensor_id": "456",
                "pollutant": "pm25",
                "value": 45.5,
                "unit": "µg/m³",
                "observed_at": "2026-08-15T12:00:00Z",
                "ingested_at": "2026-08-15T12:05:30Z",
                "raw_payload_hash": "abc123def456",
            }
        }


class RawWeatherRecord(BaseModel):
    """Raw weather observation from Open-Meteo.

    Represents hourly weather measurements from a grid point.
    Used for validation when writing to Parquet storage.

    Attributes:
        source: Source identifier (e.g., "open_meteo").
        location_id: Location/station identifier.
        observed_at: When observation was made (UTC).
        temperature_c: Temperature in Celsius.
        humidity_pct: Relative humidity (0-100%).
        wind_speed_kmh: Wind speed in km/h.
        wind_direction_deg: Wind direction in degrees (0-360).
        pressure_hpa: Barometric pressure in hPa.
        precipitation_mm: Precipitation in mm.
        cloud_cover_pct: Cloud cover (0-100%).
        ingested_at: When data was ingested (UTC).
        raw_payload_hash: SHA256 hash of raw API response.
    """

    source: str = Field(..., description="Source identifier")
    location_id: str = Field(..., description="Location/station ID")
    observed_at: datetime = Field(..., description="Observation timestamp (UTC)")
    temperature_c: float = Field(..., description="Temperature (Celsius)")
    humidity_pct: float = Field(..., description="Relative humidity (0-100%)")
    wind_speed_kmh: Optional[float] = Field(None, description="Wind speed (km/h)")
    wind_direction_deg: Optional[float] = Field(None, description="Wind direction (0-360°)")
    pressure_hpa: Optional[float] = Field(None, description="Pressure (hPa)")
    precipitation_mm: Optional[float] = Field(None, description="Precipitation (mm)")
    cloud_cover_pct: Optional[float] = Field(None, description="Cloud cover (0-100%)")
    ingested_at: datetime = Field(..., description="Ingestion timestamp (UTC)")
    raw_payload_hash: str = Field(..., description="SHA256 hash of raw payload")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "source": "open_meteo",
                "location_id": "123",
                "observed_at": "2026-08-15T12:00:00Z",
                "temperature_c": 28.5,
                "humidity_pct": 65.0,
                "wind_speed_kmh": 8.5,
                "wind_direction_deg": 180.0,
                "pressure_hpa": 1013.0,
                "precipitation_mm": 0.1,
                "cloud_cover_pct": 40.0,
                "ingested_at": "2026-08-15T12:05:30Z",
                "raw_payload_hash": "abc123def456",
            }
        }
