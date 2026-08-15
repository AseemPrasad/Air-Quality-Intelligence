#!/bin/bash
# Health check script for Air Quality Intelligence Platform
# Verifies all Docker Compose services are healthy
# Exit code: 0 if all healthy, 1 if any degraded

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================================================="
echo "Air Quality Intelligence Platform - Health Check"
echo "=========================================================================="
echo ""

# Track health status
OVERALL_STATUS=0

# Function to check service health
check_service() {
    local service=$1
    local description=$2

    echo -n "Checking $service... "

    # Get service status from docker-compose
    if docker-compose ps "$service" 2>/dev/null | grep -q "Up"; then
        echo -e "${GREEN}✓ Running${NC}"
        return 0
    else
        echo -e "${RED}✗ Not running${NC}"
        OVERALL_STATUS=1
        return 1
    fi
}

# Function to check service health from docker-compose
check_service_health() {
    local service=$1
    local description=$2

    echo -n "Checking $service health... "

    # Get the full status including (healthy) or (unhealthy)
    local status=$(docker-compose ps "$service" 2>/dev/null | tail -1 | grep -oE '\(.*\)' || echo "(unknown)")

    if echo "$status" | grep -q "healthy"; then
        echo -e "${GREEN}✓ Healthy${NC}"
        return 0
    elif echo "$status" | grep -q "starting"; then
        echo -e "${YELLOW}⊙ Starting${NC}"
        return 0
    elif echo "$status" | grep -q "unhealthy"; then
        echo -e "${RED}✗ Unhealthy${NC}"
        OVERALL_STATUS=1
        return 1
    else
        # Service might not have health check, check if running
        if docker-compose ps "$service" 2>/dev/null | grep -q "Up"; then
            echo -e "${GREEN}✓ Running${NC}"
            return 0
        else
            echo -e "${RED}✗ Not running${NC}"
            OVERALL_STATUS=1
            return 1
        fi
    fi
}

# Function to check API endpoint
check_api_endpoint() {
    local endpoint=$1
    local name=$2

    echo -n "Checking API $name... "

    if curl -sf "http://localhost:8000$endpoint" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Responding${NC}"
        return 0
    else
        echo -e "${RED}✗ Not responding${NC}"
        OVERALL_STATUS=1
        return 1
    fi
}

# Function to check database connectivity
check_database() {
    echo -n "Checking PostgreSQL connectivity... "

    if docker-compose exec -T postgres pg_isready -U ${POSTGRES_USER:-aqadmin} > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Connected${NC}"
        return 0
    else
        echo -e "${RED}✗ Cannot connect${NC}"
        OVERALL_STATUS=1
        return 1
    fi
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Service Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

check_service "postgres" "PostgreSQL database"
check_service "airflow-init" "Airflow initialization"
check_service "airflow-scheduler" "Airflow scheduler"
check_service "airflow-webserver" "Airflow webserver"
check_service "api" "FastAPI server"
check_service "dashboard" "Streamlit dashboard"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Health Checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

check_service_health "postgres" "Database"
check_service_health "airflow-scheduler" "Scheduler"
check_service_health "airflow-webserver" "Webserver"
check_service_health "api" "API"
check_service_health "dashboard" "Dashboard"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Connectivity Checks"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

check_database
check_api_endpoint "/api/system/health" "System Health"
check_api_endpoint "/api/locations" "Locations Endpoint"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Network Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Network: aq-net"
docker network ls | grep aq-net > /dev/null 2>&1 && echo -e "${GREEN}✓ Network created${NC}" || echo -e "${RED}✗ Network not found${NC}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Service URLs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "API Server:      http://localhost:8000"
echo "API Docs:        http://localhost:8000/docs"
echo "Airflow UI:      http://localhost:8080"
echo "Dashboard:       http://localhost:8501"
echo "PostgreSQL:      localhost:5432"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Resource Usage"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Container Resource Limits:"
docker-compose ps --format "table {{.Names}}\t{{.CPUs}}\t{{.MemLimit}}" 2>/dev/null | tail -n +2 || echo "Unable to retrieve resource info"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $OVERALL_STATUS -eq 0 ]; then
    echo -e "${GREEN}✓ All services healthy!${NC}"
    echo "Estimated startup time: < 2 minutes"
else
    echo -e "${RED}✗ Some services are unhealthy. Check logs:${NC}"
    echo "  docker-compose logs <service_name>"
fi

echo "=========================================================================="
echo ""

exit $OVERALL_STATUS
