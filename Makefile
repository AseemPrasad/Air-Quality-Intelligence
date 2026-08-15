.PHONY: help build up down logs clean restart test lint format install-dev

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Air Quality Intelligence Platform - Development Commands$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

install-dev: ## Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	pip install -e ".[dev]"
	pre-commit install

build: ## Build all Docker images
	@echo "$(BLUE)Building Docker images...$(NC)"
	docker-compose build

up: ## Start all services (postgres, airflow, api, dashboard)
	@echo "$(BLUE)Starting Air Quality Platform...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Services started$(NC)"
	@echo "  Postgres (5432)"
	@echo "  Airflow UI (http://localhost:8080)"
	@echo "  API (http://localhost:8000)"
	@echo "  Dashboard (http://localhost:8501)"

down: ## Stop all services
	@echo "$(BLUE)Stopping services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Services stopped$(NC)"

restart: down up ## Restart all services

logs: ## Tail logs from all services
	docker-compose logs -f

logs-api: ## Tail API logs
	docker-compose logs -f api

logs-dashboard: ## Tail dashboard logs
	docker-compose logs -f dashboard

logs-scheduler: ## Tail Airflow scheduler logs
	docker-compose logs -f airflow-scheduler

logs-postgres: ## Tail PostgreSQL logs
	docker-compose logs -f postgres

clean: ## Remove containers, volumes, and cached data
	@echo "$(YELLOW)WARNING: This will remove all containers and data!$(NC)"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v; \
		echo "$(GREEN)✓ Cleaned up$(NC)"; \
	fi

shell-postgres: ## Connect to PostgreSQL shell
	docker-compose exec postgres psql -U aqadmin -d aq_control

shell-api: ## Connect to API container shell
	docker-compose exec api bash

shell-dashboard: ## Connect to dashboard container shell
	docker-compose exec dashboard bash

test: ## Run test suite
	@echo "$(BLUE)Running tests...$(NC)"
	pytest tests/ -v --cov=src/aq_engine

test-fast: ## Run tests without coverage
	pytest tests/ -v -x

lint: ## Run linters (ruff + mypy)
	@echo "$(BLUE)Running linters...$(NC)"
	ruff check src/ tests/
	mypy src/aq_engine

format: ## Format code with black
	@echo "$(BLUE)Formatting code...$(NC)"
	black src/ tests/

format-check: ## Check code formatting without modifying
	black --check src/ tests/

db-init: ## Initialize the database schema
	@echo "$(BLUE)Initializing database...$(NC)"
	docker-compose exec postgres psql -U aqadmin -d aq_control -f /docker-entrypoint-initdb.d/01-init-control-plane.sql

db-reset: ## Drop and reinitialize the database (WARNING: deletes all data)
	@echo "$(YELLOW)WARNING: This will delete all database data!$(NC)"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose exec postgres psql -U aqadmin -d aq_control -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"; \
		docker-compose exec postgres psql -U aqadmin -d aq_control -f /docker-entrypoint-initdb.d/01-init-control-plane.sql; \
		echo "$(GREEN)✓ Database reset$(NC)"; \
	fi

airflow-init: ## Initialize Airflow database and create admin user
	@echo "$(BLUE)Initializing Airflow...$(NC)"
	docker-compose up airflow-init

env-setup: ## Create .env file from .env.example
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "$(GREEN)✓ Created .env from .env.example$(NC)"; \
		echo "$(YELLOW)! Please customize .env with your settings$(NC)"; \
	else \
		echo "$(YELLOW)! .env already exists, skipping$(NC)"; \
	fi

health: ## Check health of all services
	@echo "$(BLUE)Checking service health...$(NC)"
	@docker-compose ps
	@echo ""
	@docker-compose exec postgres pg_isready -U aqadmin && echo "$(GREEN)✓ PostgreSQL$(NC)" || echo "✗ PostgreSQL"
	@curl -s http://localhost:8000/health > /dev/null 2>&1 && echo "$(GREEN)✓ API$(NC)" || echo "✗ API"
	@curl -s http://localhost:8501/_stcore/health > /dev/null 2>&1 && echo "$(GREEN)✓ Dashboard$(NC)" || echo "✗ Dashboard"

version: ## Show project version
	@python -c "from aq_engine import __version__; print(__version__)"
