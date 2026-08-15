-- Air Quality Intelligence Platform - Control Plane Schema
-- PostgreSQL initialization script
-- This script sets up all metadata tables, relationships, and audit structures

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================================
-- SOURCE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS source (
    source_id BIGSERIAL PRIMARY KEY,
    source_name TEXT UNIQUE NOT NULL,
    source_type TEXT NOT NULL,
    base_url TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_source_active ON source(active);
CREATE INDEX idx_source_created_at ON source(created_at DESC);

-- ============================================================================
-- LOCATION TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS location (
    location_id BIGSERIAL PRIMARY KEY,
    location_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    timezone TEXT NOT NULL,
    elevation_m DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_location_city ON location(city);
CREATE INDEX idx_location_code ON location(location_code);
CREATE INDEX idx_location_country ON location(country);

-- ============================================================================
-- STATION TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS station (
    station_id BIGSERIAL PRIMARY KEY,
    source_id BIGINT REFERENCES source(source_id) ON DELETE CASCADE,
    source_station_id TEXT NOT NULL,
    location_id BIGINT REFERENCES location(location_id) ON DELETE CASCADE,
    station_name TEXT,
    station_type TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_id, source_station_id)
);

CREATE INDEX idx_station_location_id ON station(location_id);
CREATE INDEX idx_station_source_id ON station(source_id);
CREATE INDEX idx_station_is_active ON station(is_active);
CREATE INDEX idx_station_last_seen_at ON station(last_seen_at DESC);

-- ============================================================================
-- SENSOR TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS sensor (
    sensor_id BIGSERIAL PRIMARY KEY,
    station_id BIGINT REFERENCES station(station_id) ON DELETE CASCADE,
    source_sensor_id TEXT NOT NULL,
    pollutant_code TEXT NOT NULL,
    unit TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(station_id, source_sensor_id, pollutant_code)
);

CREATE INDEX idx_sensor_station_id ON sensor(station_id);
CREATE INDEX idx_sensor_pollutant_code ON sensor(pollutant_code);
CREATE INDEX idx_sensor_last_seen_at ON sensor(last_seen_at DESC);

-- ============================================================================
-- INGESTION_RUN TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS ingestion_run (
    run_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id BIGINT REFERENCES source(source_id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'partial')),
    requested_start TIMESTAMPTZ,
    requested_end TIMESTAMPTZ,
    records_received BIGINT DEFAULT 0,
    records_written BIGINT DEFAULT 0,
    records_rejected BIGINT DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ingestion_run_source_id ON ingestion_run(source_id);
CREATE INDEX idx_ingestion_run_status ON ingestion_run(status);
CREATE INDEX idx_ingestion_run_started_at ON ingestion_run(started_at DESC);
CREATE INDEX idx_ingestion_run_finished_at ON ingestion_run(finished_at DESC NULLS LAST);

-- ============================================================================
-- QUALITY_RUN TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS quality_run (
    quality_run_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    input_records BIGINT,
    valid_records BIGINT,
    suspicious_records BIGINT,
    invalid_records BIGINT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_quality_run_status ON quality_run(status);
CREATE INDEX idx_quality_run_started_at ON quality_run(started_at DESC);
CREATE INDEX idx_quality_run_finished_at ON quality_run(finished_at DESC NULLS LAST);

-- ============================================================================
-- MODEL TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS model (
    model_id BIGSERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    target TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_model_target ON model(target);
CREATE INDEX idx_model_name ON model(model_name);

-- ============================================================================
-- MODEL_VERSION TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS model_version (
    model_version_id BIGSERIAL PRIMARY KEY,
    model_id BIGINT REFERENCES model(model_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    training_start TIMESTAMPTZ NOT NULL,
    training_end TIMESTAMPTZ NOT NULL,
    mae DOUBLE PRECISION,
    rmse DOUBLE PRECISION,
    artifact_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('training', 'ready', 'active', 'deprecated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_id, version)
);

CREATE INDEX idx_model_version_model_id ON model_version(model_id);
CREATE INDEX idx_model_version_status ON model_version(status);
CREATE INDEX idx_model_version_created_at ON model_version(created_at DESC);

-- ============================================================================
-- PREDICTION TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS prediction (
    prediction_id BIGSERIAL PRIMARY KEY,
    model_version_id BIGINT REFERENCES model_version(model_version_id) ON DELETE SET NULL,
    location_id BIGINT REFERENCES location(location_id) ON DELETE CASCADE,
    generated_at TIMESTAMPTZ NOT NULL,
    target_time TIMESTAMPTZ NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    predicted_pm25 DOUBLE PRECISION,
    lower_bound DOUBLE PRECISION,
    upper_bound DOUBLE PRECISION,
    actual_pm25 DOUBLE PRECISION,
    absolute_error DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_prediction_model_version_id ON prediction(model_version_id);
CREATE INDEX idx_prediction_location_id ON prediction(location_id);
CREATE INDEX idx_prediction_generated_at ON prediction(generated_at DESC);
CREATE INDEX idx_prediction_target_time ON prediction(target_time DESC);
CREATE INDEX idx_prediction_horizon ON prediction(horizon_minutes);

-- ============================================================================
-- COMPOSITE INDEXES FOR COMMON QUERIES
-- ============================================================================
CREATE INDEX idx_ingestion_run_source_status ON ingestion_run(source_id, status);
CREATE INDEX idx_station_location_active ON station(location_id, is_active);
CREATE INDEX idx_sensor_station_pollutant ON sensor(station_id, pollutant_code);
CREATE INDEX idx_prediction_location_horizon ON prediction(location_id, horizon_minutes);

-- ============================================================================
-- AUDIT TRIGGER FUNCTION
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply audit trigger to all tables with updated_at
CREATE TRIGGER trigger_source_updated_at
    BEFORE UPDATE ON source
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_location_updated_at
    BEFORE UPDATE ON location
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_station_updated_at
    BEFORE UPDATE ON station
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_sensor_updated_at
    BEFORE UPDATE ON sensor
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_ingestion_run_updated_at
    BEFORE UPDATE ON ingestion_run
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_quality_run_updated_at
    BEFORE UPDATE ON quality_run
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_model_updated_at
    BEFORE UPDATE ON model
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_model_version_updated_at
    BEFORE UPDATE ON model_version
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_prediction_updated_at
    BEFORE UPDATE ON prediction
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Active stations with location info
CREATE OR REPLACE VIEW v_active_stations AS
SELECT
    s.station_id,
    s.station_name,
    l.location_id,
    l.location_code,
    l.city,
    l.country,
    s.latitude,
    s.longitude,
    s.last_seen_at
FROM station s
JOIN location l ON s.location_id = l.location_id
WHERE s.is_active = TRUE;

-- Recent ingestion runs
CREATE OR REPLACE VIEW v_recent_ingestion_runs AS
SELECT
    ir.run_id,
    s.source_name,
    ir.status,
    ir.records_received,
    ir.records_written,
    ir.records_rejected,
    ir.started_at,
    ir.finished_at,
    EXTRACT(EPOCH FROM (ir.finished_at - ir.started_at)) as duration_seconds
FROM ingestion_run ir
JOIN source s ON ir.source_id = s.source_id
ORDER BY ir.started_at DESC
LIMIT 100;

-- Active model versions by target
CREATE OR REPLACE VIEW v_active_models AS
SELECT
    m.model_id,
    m.model_name,
    m.target,
    mv.version,
    mv.mae,
    mv.rmse,
    mv.status,
    mv.created_at
FROM model m
JOIN model_version mv ON m.model_id = mv.model_id
WHERE mv.status = 'active';
