"""Unit tests for PostgreSQL control plane (SQLAlchemy ORM).

Tests CRUD operations, relationships, transactions, and watermark management.
Uses SQLite for testing (no external PostgreSQL required).
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aq_engine.storage.db import (
    Base,
    Database,
    Source,
    Location,
    Station,
    Sensor,
    IngestionRun,
    QualityRun,
    Model,
    ModelVersion,
    Prediction,
    LocationRepository,
    StationRepository,
    IngestionRunRepository,
)
from aq_engine.common import DatabaseError


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing."""
    # Use SQLite for testing (no external PostgreSQL needed)
    db_url = "sqlite:///:memory:"
    db = Database(db_url, echo=False)

    # Create tables
    db.create_tables()

    yield db

    # Cleanup
    db.drop_tables()


@pytest.fixture
def session(test_db):
    """Get database session."""
    with test_db.session() as s:
        yield s


class TestDatabaseConnection:
    """Test database connection management."""

    def test_create_database(self, test_db):
        """Test database creation."""
        assert test_db.engine is not None
        assert test_db.SessionLocal is not None

    def test_health_check_passes(self, test_db):
        """Test health check on healthy database."""
        assert test_db.health_check() is True

    def test_create_tables(self, test_db):
        """Test table creation."""
        # Tables already created in fixture
        with test_db.session() as session:
            # Verify at least one table exists by querying
            result = session.query(Source).first()
            assert result is None  # Empty table is OK


class TestSourceModel:
    """Test Source model and operations."""

    def test_create_source(self, session):
        """Test creating a source."""
        source = Source(
            source_name="openaq",
            source_type="air_quality",
            base_url="https://api.openaq.org/v3",
            active=True,
        )
        session.add(source)
        session.commit()

        assert source.source_id is not None
        assert source.source_name == "openaq"

    def test_source_repr(self, session):
        """Test Source __repr__."""
        source = Source(
            source_name="openaq",
            source_type="air_quality",
        )
        session.add(source)
        session.commit()

        repr_str = repr(source)
        assert "openaq" in repr_str
        assert "air_quality" in repr_str


class TestLocationModel:
    """Test Location model and operations."""

    def test_create_location(self, session):
        """Test creating a location."""
        location = Location(
            location_code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=int(22.5726 * 1e6),  # Microdegrees
            longitude=int(88.3639 * 1e6),
            timezone="Asia/Kolkata",
        )
        session.add(location)
        session.commit()

        assert location.location_id is not None
        assert location.location_code == "kolkata"


class TestStationModel:
    """Test Station model and operations."""

    def test_create_station(self, session):
        """Test creating a station."""
        # Create source first
        source = Source(source_name="openaq", source_type="air_quality")
        session.add(source)
        session.flush()

        # Create location
        location = Location(
            location_code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=int(22.5726 * 1e6),
            longitude=int(88.3639 * 1e6),
            timezone="Asia/Kolkata",
        )
        session.add(location)
        session.flush()

        # Create station
        station = Station(
            source_id=source.source_id,
            source_station_id="123",
            location_id=location.location_id,
            station_name="Test Station",
        )
        session.add(station)
        session.commit()

        assert station.station_id is not None
        assert station.source_id == source.source_id


class TestSensorModel:
    """Test Sensor model and operations."""

    def test_create_sensor(self, session):
        """Test creating a sensor."""
        # Create source, location, station
        source = Source(source_name="openaq", source_type="air_quality")
        session.add(source)
        session.flush()

        location = Location(
            location_code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=int(22.5726 * 1e6),
            longitude=int(88.3639 * 1e6),
            timezone="Asia/Kolkata",
        )
        session.add(location)
        session.flush()

        station = Station(
            source_id=source.source_id,
            source_station_id="123",
            location_id=location.location_id,
        )
        session.add(station)
        session.flush()

        # Create sensor
        sensor = Sensor(
            station_id=station.station_id,
            source_sensor_id="456",
            pollutant_code="pm25",
            unit="µg/m³",
        )
        session.add(sensor)
        session.commit()

        assert sensor.sensor_id is not None
        assert sensor.pollutant_code == "pm25"


class TestIngestionRunModel:
    """Test IngestionRun model and operations."""

    def test_create_ingestion_run(self, session):
        """Test creating an ingestion run."""
        # Create source
        source = Source(source_name="openaq", source_type="air_quality")
        session.add(source)
        session.flush()

        # Create ingestion run
        run_id = str(uuid4())
        run = IngestionRun(
            run_id=run_id,
            source_id=source.source_id,
            started_at=datetime.now(timezone.utc),
            status="running",
            records_received=100,
            records_written=95,
            records_rejected=5,
        )
        session.add(run)
        session.commit()

        assert run.run_id == run_id
        assert run.status == "running"

    def test_ingestion_run_statuses(self, session):
        """Test different ingestion run statuses."""
        source = Source(source_name="openaq", source_type="air_quality")
        session.add(source)
        session.flush()

        statuses = ["running", "success", "failed", "partial"]
        for status in statuses:
            run = IngestionRun(
                run_id=str(uuid4()),
                source_id=source.source_id,
                started_at=datetime.now(timezone.utc),
                status=status,
            )
            session.add(run)

        session.commit()

        # Verify all statuses were created
        runs = session.query(IngestionRun).all()
        assert len(runs) == 4


class TestLocationRepository:
    """Test LocationRepository CRUD operations."""

    def test_get_or_create_new_location(self, test_db):
        """Test creating new location."""
        repo = LocationRepository(test_db)

        location = repo.get_or_create(
            code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=22.5726,
            longitude=88.3639,
            timezone="Asia/Kolkata",
            elevation_m=6.0,
        )

        assert location.location_id is not None
        assert location.location_code == "kolkata"

    def test_get_or_create_existing_location(self, test_db):
        """Test retrieving existing location."""
        repo = LocationRepository(test_db)

        # Create location
        location1 = repo.get_or_create(
            code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=22.5726,
            longitude=88.3639,
            timezone="Asia/Kolkata",
        )

        # Retrieve same location
        location2 = repo.get_or_create(
            code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=22.5726,
            longitude=88.3639,
            timezone="Asia/Kolkata",
        )

        assert location1.location_id == location2.location_id


class TestStationRepository:
    """Test StationRepository CRUD operations."""

    def test_get_or_create_new_station(self, test_db):
        """Test creating new station."""
        # Create source and location first
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            session.flush()
            source_id = source.source_id

            location = Location(
                location_code="kolkata",
                name="Kolkata",
                city="Kolkata",
                country="India",
                latitude=int(22.5726 * 1e6),
                longitude=int(88.3639 * 1e6),
                timezone="Asia/Kolkata",
            )
            session.add(location)
            session.flush()
            location_id = location.location_id

        # Create station
        repo = StationRepository(test_db)
        station = repo.get_or_create(
            source_id=source_id,
            source_station_id="123",
            location_id=location_id,
            station_name="Test Station",
        )

        assert station.station_id is not None

    def test_get_or_create_existing_station(self, test_db):
        """Test retrieving existing station."""
        # Setup
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            session.flush()
            source_id = source.source_id

            location = Location(
                location_code="kolkata",
                name="Kolkata",
                city="Kolkata",
                country="India",
                latitude=int(22.5726 * 1e6),
                longitude=int(88.3639 * 1e6),
                timezone="Asia/Kolkata",
            )
            session.add(location)
            session.flush()
            location_id = location.location_id

        repo = StationRepository(test_db)

        # Create station
        station1 = repo.get_or_create(
            source_id=source_id,
            source_station_id="123",
            location_id=location_id,
        )

        # Retrieve same station
        station2 = repo.get_or_create(
            source_id=source_id,
            source_station_id="123",
            location_id=location_id,
        )

        assert station1.station_id == station2.station_id


class TestIngestionRunRepository:
    """Test IngestionRunRepository CRUD operations."""

    def test_record_ingestion_run(self, test_db):
        """Test recording ingestion run."""
        # Create source
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            session.flush()
            source_id = source.source_id

        # Record run
        repo = IngestionRunRepository(test_db)
        run_id = str(uuid4())
        started_at = datetime.now(timezone.utc)

        run = repo.record_run(
            run_id=run_id,
            source_id=source_id,
            started_at=started_at,
            status="success",
            records_received=100,
            records_written=95,
            records_rejected=5,
            requested_start=started_at,
            requested_end=started_at + timedelta(hours=6),
            finished_at=started_at + timedelta(seconds=30),
        )

        assert run.run_id == run_id
        assert run.status == "success"

    def test_get_watermark_no_history(self, test_db):
        """Test getting watermark with no history."""
        repo = IngestionRunRepository(test_db)

        # Create source
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            session.flush()
            source_id = source.source_id

        # Get watermark (should be None)
        event_time, ingestion_time = repo.get_latest_watermark(source_id)

        assert event_time is None
        assert ingestion_time is None

    def test_get_watermark_with_successful_runs(self, test_db):
        """Test getting watermark with successful runs."""
        # Create source
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            session.flush()
            source_id = source.source_id

        repo = IngestionRunRepository(test_db)

        # Record successful run
        started_at = datetime.now(timezone.utc)
        requested_end = started_at + timedelta(hours=6)
        finished_at = started_at + timedelta(seconds=30)

        repo.record_run(
            run_id=str(uuid4()),
            source_id=source_id,
            started_at=started_at,
            status="success",
            requested_start=started_at,
            requested_end=requested_end,
            finished_at=finished_at,
        )

        # Get watermark
        event_time, ingestion_time = repo.get_latest_watermark(source_id)

        assert event_time is not None
        assert ingestion_time is not None
        assert event_time == requested_end

    def test_watermark_ignores_failed_runs(self, test_db):
        """Test that watermark ignores failed runs."""
        # Create source
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            session.flush()
            source_id = source.source_id

        repo = IngestionRunRepository(test_db)
        started_at = datetime.now(timezone.utc)

        # Record failed run
        repo.record_run(
            run_id=str(uuid4()),
            source_id=source_id,
            started_at=started_at,
            status="failed",
            error_message="API error",
        )

        # Get watermark (should be None, failed runs don't advance watermark)
        event_time, ingestion_time = repo.get_latest_watermark(source_id)

        assert event_time is None
        assert ingestion_time is None


class TestTransactionManagement:
    """Test transaction handling."""

    def test_commit_on_success(self, test_db):
        """Test that changes are committed on success."""
        with test_db.session() as session:
            source = Source(source_name="openaq", source_type="air_quality")
            session.add(source)
            # Commit happens on context exit

        # Verify data persisted
        with test_db.session() as session:
            source = session.query(Source).filter_by(source_name="openaq").first()
            assert source is not None

    def test_rollback_on_error(self, test_db):
        """Test that changes are rolled back on error."""
        try:
            with test_db.session() as session:
                source = Source(source_name="openaq", source_type="air_quality")
                session.add(source)
                # Force error before commit
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify data was not persisted
        with test_db.session() as session:
            source = session.query(Source).filter_by(source_name="openaq").first()
            assert source is None


class TestRelationships:
    """Test model relationships."""

    def test_source_has_many_stations(self, session):
        """Test source-station relationship."""
        # Create source
        source = Source(source_name="openaq", source_type="air_quality")
        session.add(source)
        session.flush()

        # Create location
        location = Location(
            location_code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=int(22.5726 * 1e6),
            longitude=int(88.3639 * 1e6),
            timezone="Asia/Kolkata",
        )
        session.add(location)
        session.flush()

        # Create stations
        for i in range(3):
            station = Station(
                source_id=source.source_id,
                source_station_id=f"{i}",
                location_id=location.location_id,
            )
            session.add(station)

        session.commit()

        # Verify relationship
        assert len(source.stations) == 3

    def test_station_has_many_sensors(self, session):
        """Test station-sensor relationship."""
        # Create source, location, station
        source = Source(source_name="openaq", source_type="air_quality")
        session.add(source)
        session.flush()

        location = Location(
            location_code="kolkata",
            name="Kolkata",
            city="Kolkata",
            country="India",
            latitude=int(22.5726 * 1e6),
            longitude=int(88.3639 * 1e6),
            timezone="Asia/Kolkata",
        )
        session.add(location)
        session.flush()

        station = Station(
            source_id=source.source_id,
            source_station_id="123",
            location_id=location.location_id,
        )
        session.add(station)
        session.flush()

        # Create sensors
        for pollutant in ["pm25", "pm10", "no2"]:
            sensor = Sensor(
                station_id=station.station_id,
                source_sensor_id=f"sensor_{pollutant}",
                pollutant_code=pollutant,
                unit="µg/m³",
            )
            session.add(sensor)

        session.commit()

        # Verify relationship
        assert len(station.sensors) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
