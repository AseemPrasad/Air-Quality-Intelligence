"""Observations and locations endpoints."""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Query, HTTPException, status

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Observations"],
)


# Pydantic models
class LocationMetadata(BaseModel):
    """Location metadata."""

    location_id: str
    name: str
    city: str
    country: str
    latitude: float
    longitude: float
    timezone: str
    active_stations: int
    last_update: datetime


class LocationsResponse(BaseModel):
    """Locations list response."""

    locations: List[LocationMetadata]


class PollutantObservation(BaseModel):
    """Single pollutant observation."""

    pollutant: str
    value: float
    unit: str
    timestamp: datetime
    baseline_median: Optional[float] = None
    baseline_p95: Optional[float] = None
    anomaly_severity: Optional[str] = None
    anomaly_score: Optional[float] = None
    quality_flag: str


class WeatherObservation(BaseModel):
    """Weather observation."""

    temperature_c: float = Field(..., description="Temperature in Celsius")
    humidity_pct: float = Field(..., description="Humidity percentage (0-100)")
    wind_speed_kmh: float = Field(..., description="Wind speed in km/h")
    wind_direction_deg: float = Field(..., description="Wind direction in degrees (0-360)")
    timestamp: datetime


class DataFreshness(BaseModel):
    """Data freshness information."""

    data_age_minutes: int
    expected_interval_minutes: int
    status: str  # "fresh", "stale", "missing"


class CurrentObservationResponse(BaseModel):
    """Current observations response."""

    location_id: str
    current_time: datetime
    pollutants: List[PollutantObservation]
    weather: Optional[WeatherObservation] = None
    freshness: DataFreshness


class HistoricalDataPoint(BaseModel):
    """Single historical data point."""

    hour_start: Optional[datetime] = None
    day_start: Optional[datetime] = None
    mean_value: float
    median_value: float
    min_value: float
    max_value: float
    observation_count: int
    coverage_pct: float
    baseline_median: Optional[float] = None


class HistoryResponse(BaseModel):
    """History time series response."""

    location_id: str
    pollutant: str
    grain: str  # "hourly", "daily"
    start_date: datetime
    end_date: datetime
    data: List[HistoricalDataPoint]


# Mock data
MOCK_LOCATIONS = [
    LocationMetadata(
        location_id="kolkata_001",
        name="Kolkata Center",
        city="Kolkata",
        country="India",
        latitude=22.5726,
        longitude=88.3639,
        timezone="Asia/Kolkata",
        active_stations=3,
        last_update=datetime(2026, 8, 15, 10, 30, tzinfo=timezone.utc),
    ),
    LocationMetadata(
        location_id="delhi_001",
        name="Delhi Central",
        city="Delhi",
        country="India",
        latitude=28.7041,
        longitude=77.1025,
        timezone="Asia/Kolkata",
        active_stations=5,
        last_update=datetime(2026, 8, 15, 10, 25, tzinfo=timezone.utc),
    ),
]


# Routes
@router.get(
    "/locations",
    response_model=LocationsResponse,
    summary="List all locations",
    description="Get list of all monitoring locations with metadata",
)
async def get_locations() -> LocationsResponse:
    """Get all monitoring locations.

    Returns:
        List of locations with metadata
    """
    logger.info("Fetching all locations")
    return LocationsResponse(locations=MOCK_LOCATIONS)


@router.get(
    "/locations/{location_id}/current",
    response_model=CurrentObservationResponse,
    summary="Current observations",
    description="Get latest observations for a location including quality and anomaly info",
)
async def get_current_observation(location_id: str) -> CurrentObservationResponse:
    """Get current observations for a location.

    Args:
        location_id: Location identifier

    Returns:
        Current observations with pollutants and weather

    Raises:
        HTTPException: 404 if location not found
    """
    # Check location exists
    location = next(
        (loc for loc in MOCK_LOCATIONS if loc.location_id == location_id),
        None,
    )
    if not location:
        logger.warning(f"Location not found: {location_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {location_id} not found",
        )

    current_time = datetime.now(timezone.utc)
    observation_time = current_time.replace(minute=0, second=0, microsecond=0)

    # Mock pollutant data
    pollutants = [
        PollutantObservation(
            pollutant="PM2.5",
            value=65.5,
            unit="µg/m³",
            timestamp=observation_time,
            baseline_median=55.0,
            baseline_p95=80.0,
            anomaly_severity="HIGH",
            anomaly_score=3.2,
            quality_flag="VALID",
        ),
        PollutantObservation(
            pollutant="PM10",
            value=120.3,
            unit="µg/m³",
            timestamp=observation_time,
            baseline_median=100.0,
            baseline_p95=150.0,
            anomaly_severity="NORMAL",
            anomaly_score=0.8,
            quality_flag="VALID",
        ),
    ]

    # Mock weather data
    weather = WeatherObservation(
        temperature_c=32.5,
        humidity_pct=75,
        wind_speed_kmh=12.0,
        wind_direction_deg=230.0,
        timestamp=observation_time,
    )

    # Data freshness
    data_age_minutes = int((current_time - observation_time).total_seconds() / 60)
    freshness = DataFreshness(
        data_age_minutes=data_age_minutes,
        expected_interval_minutes=5,
        status="fresh" if data_age_minutes <= 10 else "stale",
    )

    logger.info(f"Current observations fetched for {location_id}")

    return CurrentObservationResponse(
        location_id=location_id,
        current_time=current_time,
        pollutants=pollutants,
        weather=weather,
        freshness=freshness,
    )


@router.get(
    "/locations/{location_id}/history",
    response_model=HistoryResponse,
    summary="Historical observations",
    description="Get time series of observations for a location",
)
async def get_history(
    location_id: str,
    start_date: datetime = Query(..., description="Start date (ISO 8601)"),
    end_date: datetime = Query(..., description="End date (ISO 8601)"),
    pollutant: str = Query("PM2.5", description="Pollutant name"),
    grain: str = Query("hourly", regex="^(hourly|daily)$", description="Time grain"),
) -> HistoryResponse:
    """Get historical observations for a location.

    Args:
        location_id: Location identifier
        start_date: Start date (ISO 8601)
        end_date: End date (ISO 8601)
        pollutant: Pollutant name (default: PM2.5)
        grain: Time grain (hourly or daily)

    Returns:
        Time series of observations

    Raises:
        HTTPException: 404 if location not found
        HTTPException: 400 if date range invalid
        HTTPException: 422 if parameters missing
    """
    # Check location exists
    location = next(
        (loc for loc in MOCK_LOCATIONS if loc.location_id == location_id),
        None,
    )
    if not location:
        logger.warning(f"Location not found: {location_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {location_id} not found",
        )

    # Validate date range
    if end_date < start_date:
        logger.warning(f"Invalid date range: {start_date} to {end_date}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be after start date",
        )

    # Generate mock historical data
    data_points = []
    current = start_date

    if grain == "hourly":
        while current <= end_date:
            data_points.append(
                HistoricalDataPoint(
                    hour_start=current,
                    mean_value=58.2 + (current.hour % 10),
                    median_value=57.5 + (current.hour % 10),
                    min_value=42.1,
                    max_value=75.3,
                    observation_count=12,
                    coverage_pct=100.0,
                    baseline_median=55.0,
                )
            )
            current += timedelta(hours=1)
    else:  # daily
        while current <= end_date:
            data_points.append(
                HistoricalDataPoint(
                    day_start=current,
                    mean_value=60.0 + (current.day % 10),
                    median_value=59.0 + (current.day % 10),
                    min_value=40.0,
                    max_value=85.0,
                    observation_count=288,
                    coverage_pct=98.0,
                    baseline_median=55.0,
                )
            )
            current += timedelta(days=1)

    logger.info(
        f"History fetched for {location_id}/{pollutant} "
        f"({start_date} to {end_date}, {len(data_points)} points)"
    )

    return HistoryResponse(
        location_id=location_id,
        pollutant=pollutant,
        grain=grain,
        start_date=start_date,
        end_date=end_date,
        data=data_points,
    )
