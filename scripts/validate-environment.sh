#!/bin/bash
# Environment validation script
# Checks if all required environment variables and dependencies are present

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

echo "=========================================="
echo "Environment Validation"
echo "=========================================="
echo ""

# Check if .env file exists
echo "Checking environment configuration..."
if [ -f .env ]; then
    echo -e "  ${GREEN}✓${NC} .env file found"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo -e "  ${YELLOW}⚠${NC} .env file not found (using .env.example defaults)"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""
echo "Checking required environment variables..."
echo "----------------------------------------"

# Required variables
REQUIRED_VARS=(
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
    "OPENAQ_API_KEY"
)

for var in "${REQUIRED_VARS[@]}"; do
    echo -n "  $var... "
    if [ -z "${!var}" ]; then
        echo -e "${RED}MISSING${NC}"
        ERRORS=$((ERRORS + 1))
    else
        # Mask password
        if [[ $var == *"PASSWORD"* ]] || [[ $var == *"KEY"* ]]; then
            echo -e "${GREEN}SET (hidden)${NC}"
        else
            echo -e "${GREEN}${!var}${NC}"
        fi
    fi
done

echo ""
echo "Checking system dependencies..."
echo "----------------------------------------"

# Check Docker
echo -n "  Docker... "
if command -v docker &> /dev/null; then
    VERSION=$(docker --version | awk '{print $3}' | tr -d ',')
    echo -e "${GREEN}$VERSION${NC}"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check Docker Compose
echo -n "  Docker Compose... "
if command -v docker-compose &> /dev/null; then
    VERSION=$(docker-compose --version | awk '{print $4}' | tr -d ',')
    echo -e "${GREEN}$VERSION${NC}"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check Python
echo -n "  Python... "
if command -v python3 &> /dev/null; then
    VERSION=$(python3 --version | awk '{print $2}')
    if [[ $VERSION == 3.12* ]]; then
        echo -e "${GREEN}$VERSION${NC}"
    else
        echo -e "${YELLOW}$VERSION (3.12 recommended)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check psql
echo -n "  PostgreSQL Client (psql)... "
if command -v psql &> /dev/null; then
    VERSION=$(psql --version | awk '{print $3}')
    echo -e "${GREEN}$VERSION${NC}"
else
    echo -e "${YELLOW}NOT FOUND (optional)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# Check make
echo -n "  GNU Make... "
if command -v make &> /dev/null; then
    VERSION=$(make --version | head -1 | awk '{print $3}')
    echo -e "${GREEN}$VERSION${NC}"
else
    echo -e "${YELLOW}NOT FOUND (optional)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""
echo "Checking directory structure..."
echo "----------------------------------------"

# Check required directories
REQUIRED_DIRS=(
    "configs"
    "dags"
    "docker"
    "src/aq_engine"
    "tests"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    echo -n "  $dir... "
    if [ -d "$dir" ]; then
        echo -e "${GREEN}EXISTS${NC}"
    else
        echo -e "${RED}MISSING${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "Checking data directories..."
echo "----------------------------------------"

# Create data directories if they don't exist
DATA_DIRS=(
    "data/raw"
    "data/checkpoints"
    "logs"
)

for dir in "${DATA_DIRS[@]}"; do
    echo -n "  $dir... "
    if [ -d "$dir" ]; then
        echo -e "${GREEN}EXISTS${NC}"
    else
        echo -e "${YELLOW}CREATING${NC}"
        mkdir -p "$dir"
        WARNINGS=$((WARNINGS + 1))
    fi
done

echo ""
echo "Checking configuration files..."
echo "----------------------------------------"

CONFIG_FILES=(
    "configs/default.yaml"
    "configs/logging.yaml"
    "configs/sources/openaq.yaml"
    "configs/sources/open_meteo.yaml"
    "docker-compose.yml"
    "pyproject.toml"
)

for file in "${CONFIG_FILES[@]}"; do
    echo -n "  $file... "
    if [ -f "$file" ]; then
        echo -e "${GREEN}EXISTS${NC}"
    else
        echo -e "${RED}MISSING${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "Checking Docker network..."
echo "----------------------------------------"

echo -n "  aq-net network... "
if docker network ls | grep -q "aq-net"; then
    echo -e "${GREEN}EXISTS${NC}"
else
    echo -e "${YELLOW}NOT CREATED (will be created on startup)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""
echo "Checking port availability..."
echo "----------------------------------------"

check_port() {
    local port=$1
    local service=$2
    echo -n "  Port $port ($service)... "
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${YELLOW}IN USE${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${GREEN}AVAILABLE${NC}"
    fi
}

check_port 5432 "PostgreSQL"
check_port 8000 "API"
check_port 8080 "Airflow"
check_port 8501 "Dashboard"

echo ""
echo "Checking disk space..."
echo "----------------------------------------"

AVAILABLE=$(df -h . | awk 'NR==2 {print $4}')
echo "  Available space: $AVAILABLE"

echo ""
echo "=========================================="
echo "Validation Summary"
echo "=========================================="
echo ""
echo -e "Errors:   ${RED}$ERRORS${NC}"
echo -e "Warnings: ${YELLOW}$WARNINGS${NC}"
echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}✗ Environment validation failed${NC}"
    echo "Please fix errors before starting the platform"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}⚠ Environment validation passed with warnings${NC}"
    echo "Review warnings before starting the platform"
    exit 0
else
    echo -e "${GREEN}✓ Environment validation passed${NC}"
    echo "Ready to start the platform"
    exit 0
fi
