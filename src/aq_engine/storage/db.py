"""PostgreSQL control plane with SQLAlchemy ORM.

Provides ORM models and CRUD operations for metadata, lineage, and state management.
Includes transaction management, connection pooling, and error handling.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    create_engine,
    func,
    event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker,
    Session,
)
from sqlalchemy.pool import QueuePool
import contextlib

from aq_engine.common import ensure_utc, DatabaseError


logger = logging.getLogger(__name__)

Base = declarative_base()


# ============================================================================
# ORM MODELS
# ============================================================================


class Source(Base):
    """Data source (OpenAQ, Open-Meteo, etc.)."""

    __tablename__ = "source"

    source_id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_name = Column(String(255), unique=True, nullable=False)
    source_type = Column(String(50), nullable=False)  # air_quality, weather
    base_url = Column(String(255))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    stations = relationship("Station", back_populates="source", cascade="all, delete-orphan")
    ingestion_runs = relationship("IngestionRun", back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Source {self.source_id}: {self.source_name} ({self.source_type})>"


class Location(Base):
    """Geographic location (city, region)."""

    __tablename__ = "location"

    location_id = Column(BigInteger, primary_key=True, autoincrement=True)
    location_code = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    country = Column(String(100), nullable=False)
    latitude = Column(BigInteger)  # In microdegrees (int) for precision
    longitude = Column(BigInteger)  # In microdegrees (int) for precision
    timezone = Column(String(50), nullable=False)
    elevation_m = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    stations = relationship("Station", back_populates="location", cascade="all, delete-orphan")
    predictions = relationship("Prediction", back_populates="location", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Location {self.location_id}: {self.city}, {self.country}>"


class Station(Base):
    """Air quality monitoring station."""

    __tablename__ = "station"

    station_id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_id = Column(BigInteger, ForeignKey("source.source_id"), nullable=False)
    source_station_id = Column(String(255), nullable=False)
    location_id = Column(BigInteger, ForeignKey("location.location_id"), nullable=False)
    station_name = Column(String(255))
    station_type = Column(String(100))
    latitude = Column(BigInteger)  # Microdegrees
    longitude = Column(BigInteger)  # Microdegrees
    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    source = relationship("Source", back_populates="stations")
    location = relationship("Location", back_populates="stations")
    sensors = relationship("Sensor", back_populates="station", cascade="all, delete-orphan")

    __table_args__ = (
        ("unique", "source_id", "source_station_id"),  # Unique per source
    )

    def __repr__(self) -> str:
        return f"<Station {self.station_id}: {self.station_name}>"


class Sensor(Base):
    """Individual sensor within a station."""

    __tablename__ = "sensor"

    sensor_id = Column(BigInteger, primary_key=True, autoincrement=True)
    station_id = Column(BigInteger, ForeignKey("station.station_id"), nullable=False)
    source_sensor_id = Column(String(255), nullable=False)
    pollutant_code = Column(String(50), nullable=False)
    unit = Column(String(50), nullable=False)
    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    station = relationship("Station", back_populates="sensors")

    __table_args__ = (
        ("unique", "station_id", "source_sensor_id", "pollutant_code"),
    )

    def __repr__(self) -> str:
        return f"<Sensor {self.sensor_id}: {self.pollutant_code}>"


class IngestionRun(Base):
    """Record of a single ingestion operation."""

    __tablename__ = "ingestion_run"

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(BigInteger, ForeignKey("source.source_id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False)  # running, success, failed, partial
    requested_start = Column(DateTime(timezone=True))
    requested_end = Column(DateTime(timezone=True))
    records_received = Column(BigInteger, default=0)
    records_written = Column(BigInteger, default=0)
    records_rejected = Column(BigInteger, default=0)
    error_message = Column(String(1024))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    source = relationship("Source", back_populates="ingestion_runs")

    def __repr__(self) -> str:
        return f"<IngestionRun {self.run_id}: {self.status}>"


class QualityRun(Base):
    """Record of a quality validation operation."""

    __tablename__ = "quality_run"

    quality_run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    input_records = Column(BigInteger)
    valid_records = Column(BigInteger)
    suspicious_records = Column(BigInteger)
    invalid_records = Column(BigInteger)
    status = Column(String(20), nullable=False)  # running, success, failed
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<QualityRun {self.quality_run_id}: {self.status}>"


class Model(Base):
    """ML model (target + type)."""

    __tablename__ = "model"

    model_id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_name = Column(String(255), nullable=False)
    model_type = Column(String(100), nullable=False)  # linear, random_forest, xgboost
    target = Column(String(100), nullable=False)  # pm25_1h, pm25_3h, etc.
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    versions = relationship("ModelVersion", back_populates="model", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Model {self.model_id}: {self.model_name} ({self.target})>"


class ModelVersion(Base):
    """Specific version of a model."""

    __tablename__ = "model_version"

    model_version_id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_id = Column(BigInteger, ForeignKey("model.model_id"), nullable=False)
    version = Column(String(50), nullable=False)
    feature_version = Column(String(50), nullable=False)
    training_start = Column(DateTime(timezone=True), nullable=False)
    training_end = Column(DateTime(timezone=True), nullable=False)
    mae = Column(BigInteger)  # In 100ths (precision)
    rmse = Column(BigInteger)  # In 100ths (precision)
    artifact_path = Column(String(1024), nullable=False)
    status = Column(String(20), nullable=False)  # training, ready, active, deprecated
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    model = relationship("Model", back_populates="versions")
    predictions = relationship("Prediction", back_populates="model_version")

    __table_args__ = (
        ("unique", "model_id", "version"),
    )

    def __repr__(self) -> str:
        return f"<ModelVersion {self.model_version_id}: v{self.version} ({self.status})>"


class Prediction(Base):
    """Model prediction for a location/time."""

    __tablename__ = "prediction"

    prediction_id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_version_id = Column(BigInteger, ForeignKey("model_version.model_version_id"))
    location_id = Column(BigInteger, ForeignKey("location.location_id"), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=False)
    horizon_minutes = Column(BigInteger, nullable=False)
    predicted_pm25 = Column(BigInteger)  # In 100ths (precision)
    lower_bound = Column(BigInteger)  # In 100ths (precision)
    upper_bound = Column(BigInteger)  # In 100ths (precision)
    actual_pm25 = Column(BigInteger)  # In 100ths (precision)
    absolute_error = Column(BigInteger)  # In 100ths (precision)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    model_version = relationship("ModelVersion", back_populates="predictions")
    location = relationship("Location", back_populates="predictions")

    def __repr__(self) -> str:
        return f"<Prediction {self.prediction_id}: {self.target_time}>"


# ============================================================================
# DATABASE ENGINE & SESSION MANAGEMENT
# ============================================================================


class Database:
    """PostgreSQL database connection management.

    Handles engine creation, session pooling, transaction management,
    and connection health checks.
    """

    def __init__(self, database_url: str, echo: bool = False):
        """Initialize database.

        Args:
            database_url: PostgreSQL connection string.
            echo: Whether to log SQL statements.

        Raises:
            ValueError: If connection string is invalid.
        """
        if not database_url:
            raise ValueError("database_url cannot be empty")

        self.database_url = database_url
        self.echo = echo

        # Create engine with connection pooling
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Health check before each use
            pool_recycle=3600,  # Recycle connections every hour
            echo=echo,
        )

        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

        logger.info(f"Database initialized: {database_url}")

    def create_tables(self) -> None:
        """Create all tables in database.

        Raises:
            DatabaseError: On creation failure.
        """
        try:
            Base.metadata.create_all(self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            raise DatabaseError(
                f"Failed to create database tables: {str(e)}",
                context={"database_url": self.database_url},
            ) from e

    def drop_tables(self) -> None:
        """Drop all tables in database.

        Warning: Destructive operation! Use only in testing.

        Raises:
            DatabaseError: On drop failure.
        """
        try:
            Base.metadata.drop_all(self.engine)
            logger.warning("Database tables dropped")
        except Exception as e:
            raise DatabaseError(
                f"Failed to drop database tables: {str(e)}",
                context={"database_url": self.database_url},
            ) from e

    def health_check(self) -> bool:
        """Check if database is accessible.

        Returns:
            True if database is healthy, False otherwise.
        """
        try:
            with self.engine.connect() as conn:
                conn.execute("SELECT 1")
            logger.debug("Database health check passed")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    @contextlib.contextmanager
    def session(self):
        """Context manager for database session.

        Usage:
            >>> with db.session() as session:
            ...     # Perform database operations
            ...     source = session.query(Source).first()

        Yields:
            SQLAlchemy Session.

        Raises:
            DatabaseError: On transaction failure.
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except IntegrityError as e:
            session.rollback()
            # Don't raise; let caller handle idempotency
            logger.debug(f"Integrity constraint violation (expected for idempotency): {e}")
        except SQLAlchemyError as e:
            session.rollback()
            raise DatabaseError(
                f"Database error: {str(e)}",
                context={"error_type": type(e).__name__},
            ) from e
        except Exception as e:
            session.rollback()
            raise DatabaseError(
                f"Unexpected database error: {str(e)}",
                context={"error_type": type(e).__name__},
            ) from e
        finally:
            session.close()


# ============================================================================
# CRUD OPERATIONS
# ============================================================================


class LocationRepository:
    """CRUD operations for locations."""

    def __init__(self, db: Database):
        """Initialize repository.

        Args:
            db: Database instance.
        """
        self.db = db

    def get_or_create(
        self,
        code: str,
        name: str,
        city: str,
        country: str,
        latitude: float,
        longitude: float,
        timezone: str,
        elevation_m: Optional[float] = None,
    ) -> Location:
        """Get existing location or create new one.

        Args:
            code: Location code (unique).
            name: Location name.
            city: City name.
            country: Country name.
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            timezone: IANA timezone (e.g., "Asia/Kolkata").
            elevation_m: Elevation in meters (optional).

        Returns:
            Location object.

        Raises:
            DatabaseError: On database error.
        """
        try:
            with self.db.session() as session:
                location = session.query(Location).filter_by(location_code=code).first()

                if location:
                    logger.debug(f"Found existing location: {code}")
                    return location

                # Create new location
                location = Location(
                    location_code=code,
                    name=name,
                    city=city,
                    country=country,
                    latitude=int(latitude * 1e6),  # Convert to microdegrees
                    longitude=int(longitude * 1e6),
                    timezone=timezone,
                    elevation_m=int(elevation_m * 1e3) if elevation_m else None,
                )
                session.add(location)
                session.flush()  # Get the ID

                logger.info(f"Created location: {code}")
                return location

        except DatabaseError:
            raise
        except Exception as e:
            raise DatabaseError(
                f"Failed to get or create location: {str(e)}",
                context={"code": code, "city": city},
            ) from e


class StationRepository:
    """CRUD operations for stations."""

    def __init__(self, db: Database):
        """Initialize repository.

        Args:
            db: Database instance.
        """
        self.db = db

    def get_or_create(
        self,
        source_id: int,
        source_station_id: str,
        location_id: int,
        station_name: Optional[str] = None,
        station_type: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Station:
        """Get existing station or create new one.

        Args:
            source_id: Source identifier.
            source_station_id: Station ID from source.
            location_id: Location identifier.
            station_name: Station name (optional).
            station_type: Station type (optional).
            latitude: Latitude (optional).
            longitude: Longitude (optional).

        Returns:
            Station object.

        Raises:
            DatabaseError: On database error.
        """
        try:
            with self.db.session() as session:
                station = (
                    session.query(Station)
                    .filter_by(source_id=source_id, source_station_id=source_station_id)
                    .first()
                )

                if station:
                    logger.debug(f"Found existing station: {source_id}/{source_station_id}")
                    return station

                # Create new station
                station = Station(
                    source_id=source_id,
                    source_station_id=source_station_id,
                    location_id=location_id,
                    station_name=station_name,
                    station_type=station_type,
                    latitude=int(latitude * 1e6) if latitude else None,
                    longitude=int(longitude * 1e6) if longitude else None,
                    first_seen_at=datetime.now(timezone.utc),
                )
                session.add(station)
                session.flush()

                logger.info(f"Created station: {source_id}/{source_station_id}")
                return station

        except DatabaseError:
            raise
        except Exception as e:
            raise DatabaseError(
                f"Failed to get or create station: {str(e)}",
                context={"source_id": source_id, "source_station_id": source_station_id},
            ) from e


class IngestionRunRepository:
    """CRUD operations for ingestion runs."""

    def __init__(self, db: Database):
        """Initialize repository.

        Args:
            db: Database instance.
        """
        self.db = db

    def record_run(
        self,
        run_id: str,
        source_id: int,
        started_at: datetime,
        status: str,
        records_received: int = 0,
        records_written: int = 0,
        records_rejected: int = 0,
        error_message: Optional[str] = None,
        requested_start: Optional[datetime] = None,
        requested_end: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> IngestionRun:
        """Record ingestion run.

        Args:
            run_id: Run identifier (UUID).
            source_id: Source identifier.
            started_at: Run start time (UTC).
            status: Run status (running, success, failed, partial).
            records_received: Total records fetched (default 0).
            records_written: Records successfully written (default 0).
            records_rejected: Records rejected (default 0).
            error_message: Error message if failed (optional).
            requested_start: Query window start (optional).
            requested_end: Query window end (optional).
            finished_at: Run end time (optional).

        Returns:
            IngestionRun object.

        Raises:
            DatabaseError: On database error.
        """
        try:
            started_at = ensure_utc(started_at)
            if finished_at:
                finished_at = ensure_utc(finished_at)
            if requested_start:
                requested_start = ensure_utc(requested_start)
            if requested_end:
                requested_end = ensure_utc(requested_end)

            with self.db.session() as session:
                run = IngestionRun(
                    run_id=run_id,
                    source_id=source_id,
                    started_at=started_at,
                    status=status,
                    records_received=records_received,
                    records_written=records_written,
                    records_rejected=records_rejected,
                    error_message=error_message,
                    requested_start=requested_start,
                    requested_end=requested_end,
                    finished_at=finished_at,
                )
                session.add(run)
                session.flush()

                logger.info(
                    f"Recorded ingestion run: {run_id} (status={status}, "
                    f"written={records_written}, rejected={records_rejected})"
                )
                return run

        except DatabaseError:
            raise
        except Exception as e:
            raise DatabaseError(
                f"Failed to record ingestion run: {str(e)}",
                context={"run_id": str(run_id), "source_id": source_id},
            ) from e

    def get_latest_watermark(self, source_id: int) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Get latest successful ingestion times.

        Returns the most recent ingestion timestamps for determining query windows.

        Args:
            source_id: Source identifier.

        Returns:
            Tuple of (last_event_time, last_ingestion_time) or (None, None) if no successful run.

        Raises:
            DatabaseError: On database error.
        """
        try:
            with self.db.session() as session:
                run = (
                    session.query(IngestionRun)
                    .filter_by(source_id=source_id, status="success")
                    .order_by(IngestionRun.finished_at.desc())
                    .first()
                )

                if not run or not run.requested_end:
                    logger.debug(f"No watermark found for source {source_id}")
                    return None, None

                logger.debug(
                    f"Watermark for source {source_id}: "
                    f"event_time={run.requested_end}, ingestion_time={run.finished_at}"
                )
                return run.requested_end, run.finished_at

        except DatabaseError:
            raise
        except Exception as e:
            raise DatabaseError(
                f"Failed to get watermark: {str(e)}",
                context={"source_id": source_id},
            ) from e
