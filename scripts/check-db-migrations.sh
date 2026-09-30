#!/bin/bash
# Database migration status checker
# Verifies schema is up-to-date and migrations are applied

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Database Migration Status Check"
echo "=========================================="
echo ""

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-aq_control}"
DB_USER="${POSTGRES_USER:-aqadmin}"

echo "Database: ${DB_NAME}@${DB_HOST}:${DB_PORT}"
echo ""

# Check if psql is available
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: psql command not found${NC}"
    echo "Install PostgreSQL client tools"
    exit 1
fi

# Test connection
echo -n "Testing database connection... "
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED${NC}"
    echo "Cannot connect to database"
    exit 1
fi

echo ""
echo "Checking schema tables..."
echo "----------------------------------------"

# Check if required tables exist
REQUIRED_TABLES=(
    "source"
    "location"
    "station"
    "sensor"
    "ingestion_run"
    "model_version"
    "prediction"
)

MISSING_TABLES=()

for table in "${REQUIRED_TABLES[@]}"; do
    echo -n "  Checking table '$table'... "
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '$table')" | grep -q t; then
        echo -e "${GREEN}EXISTS${NC}"
    else
        echo -e "${RED}MISSING${NC}"
        MISSING_TABLES+=("$table")
    fi
done

echo ""

if [ ${#MISSING_TABLES[@]} -eq 0 ]; then
    echo -e "${GREEN}All required tables exist${NC}"
else
    echo -e "${RED}Missing tables: ${MISSING_TABLES[*]}${NC}"
    echo ""
    echo "To create schema, run:"
    echo "  psql -h $DB_HOST -U $DB_USER -d $DB_NAME < sql/schema.sql"
    exit 1
fi

echo ""
echo "Checking table indexes..."
echo "----------------------------------------"

# Check for important indexes
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 
    schemaname,
    tablename,
    indexname
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
" | head -20

echo ""
echo "Checking table row counts..."
echo "----------------------------------------"

for table in "${REQUIRED_TABLES[@]}"; do
    COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT COUNT(*) FROM $table" 2>/dev/null || echo "0")
    echo "  $table: $COUNT rows"
done

echo ""
echo "Checking alembic migration status..."
echo "----------------------------------------"

# Check if alembic_version table exists
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version')" | grep -q t; then
    echo "Alembic version table exists"
    CURRENT_VERSION=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT version_num FROM alembic_version" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$CURRENT_VERSION" ]; then
        echo -e "Current migration: ${GREEN}$CURRENT_VERSION${NC}"
    else
        echo -e "${YELLOW}No migrations applied yet${NC}"
    fi
else
    echo -e "${YELLOW}Alembic not initialized${NC}"
    echo "To initialize alembic:"
    echo "  alembic upgrade head"
fi

echo ""
echo "Database constraints check..."
echo "----------------------------------------"

# Check foreign key constraints
CONSTRAINT_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "
SELECT COUNT(*) 
FROM information_schema.table_constraints 
WHERE constraint_type = 'FOREIGN KEY' 
AND table_schema = 'public';
" | tr -d '[:space:]')

echo "Foreign key constraints: $CONSTRAINT_COUNT"

# Check unique constraints
UNIQUE_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "
SELECT COUNT(*) 
FROM information_schema.table_constraints 
WHERE constraint_type = 'UNIQUE' 
AND table_schema = 'public';
" | tr -d '[:space:]')

echo "Unique constraints: $UNIQUE_COUNT"

echo ""
echo "=========================================="
echo -e "${GREEN}Database schema check complete${NC}"
echo "=========================================="
