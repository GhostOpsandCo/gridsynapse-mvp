# GridSynapse MVP - Development Makefile
# Quick commands for development and deployment

.PHONY: help install dev test clean docker-up docker-down deploy-local docs \
	v2-install v2-api v2-web v2-test v2-build v2-benchmark v2-check v2-docker-up v2-docker-down

# Default target
help:
	@echo "GridSynapse MVP - Available Commands:"
	@echo "  make install      - Install all dependencies"
	@echo "  make dev          - Run development server"
	@echo "  make test         - Run all tests"
	@echo "  make docker-up    - Start all services with Docker Compose"
	@echo "  make docker-down  - Stop all Docker services"
	@echo "  make k8s-local    - Deploy to local Minikube"
	@echo "  make clean        - Clean up generated files"
	@echo "  make docs         - Generate API documentation"
	@echo "  make v2-install   - Install the v2 Python and web dependencies"
	@echo "  make v2-api       - Run the v2 FastAPI service on port 8080"
	@echo "  make v2-web       - Run the v2 operator console on port 3020"
	@echo "  make v2-check     - Run all v2 quality, test, build, and benchmark gates"
	@echo "  make v2-docker-up - Run the isolated v2 stack with Docker Compose"

# GridSynapse v2 commands are isolated from the legacy MVP targets above.
V2_PYTHONPATH=packages/contracts:packages/optimizer:packages/adapters:packages/explanations:services/api
V2_VENV?=.venv

v2-install:
	python3 -m venv $(V2_VENV)
	$(V2_VENV)/bin/python -m pip install --upgrade pip
	$(V2_VENV)/bin/python -m pip install -e ".[dev]"
	cd apps/web && npm ci

v2-api:
	PYTHONPATH=$(V2_PYTHONPATH) $(V2_VENV)/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

v2-web:
	cd apps/web && npm run dev

v2-test:
	$(V2_VENV)/bin/pytest

v2-build:
	cd apps/web && npm run typecheck && npm run build

v2-benchmark:
	$(V2_VENV)/bin/python scripts/run_benchmark.py

v2-check:
	$(V2_VENV)/bin/ruff format --check packages services tests/v2 scripts
	$(V2_VENV)/bin/ruff check packages services tests/v2 scripts
	$(V2_VENV)/bin/pytest
	cd apps/web && npm run typecheck && npm run build
	$(V2_VENV)/bin/python scripts/run_benchmark.py --iterations 5 --warmups 1

v2-docker-up:
	docker compose -f docker-compose.v2.yml up --build

v2-docker-down:
	docker compose -f docker-compose.v2.yml down

# Install dependencies
install:
	@echo "🚀 Installing GridSynapse dependencies..."
	cd api && pip install -r requirements.txt
	cd solver && pip install -r requirements.txt
	cd agents && pip install -r requirements.txt
	@echo "✅ Dependencies installed!"

# Development server
dev:
	@echo "🔧 Starting GridSynapse development server..."
	docker-compose up -d postgres redis
	cd api && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run tests
test:
	@echo "🧪 Running tests..."
	cd api && pytest tests/ -v --cov=.
	cd solver && pytest tests/ -v --cov=.
	cd agents && pytest tests/ -v --cov=.
	@echo "✅ All tests passed!"

# Linting and formatting
lint:
	@echo "🧹 Running linters..."
	black api/ solver/ agents/
	isort api/ solver/ agents/
	ruff check api/ solver/ agents/ --fix
	mypy api/ solver/ --ignore-missing-imports

# Security scan
security:
	@echo "🔒 Running security scan..."
	bandit -r api/ solver/ agents/
	safety check

# Docker commands
docker-up:
	@echo "🐳 Starting Docker services..."
	docker-compose up -d
	@echo "✅ Services running!"
	@echo "API: http://localhost:8000"
	@echo "Grafana: http://localhost:3000 (admin/admin)"
	@echo "Prometheus: http://localhost:9090"

docker-down:
	@echo "🛑 Stopping Docker services..."
	docker-compose down
	@echo "✅ Services stopped!"

docker-build:
	@echo "🏗️ Building Docker images..."
	docker-compose build

# Kubernetes local deployment
k8s-local:
	@echo "☸️ Deploying to Minikube..."
	minikube start --cpus=4 --memory=8192
	kubectl apply -k k8s/overlays/dev
	@echo "✅ Deployed to Minikube!"
	@echo "Run 'minikube service gridsynapse-api' to access"

k8s-delete:
	@echo "🗑️ Removing from Minikube..."
	kubectl delete -k k8s/overlays/dev

# Database operations
db-migrate:
	@echo "📊 Running database migrations..."
	cd api && alembic upgrade head

db-reset:
	@echo "⚠️ Resetting database..."
	cd api && alembic downgrade base && alembic upgrade head

# Generate API documentation
docs:
	@echo "📚 Generating documentation..."
	cd api && python -m pdoc --html --output-dir ../docs/api .
	@echo "✅ Documentation generated in docs/"

# Performance testing
perf-test:
	@echo "⚡ Running performance tests..."
	cd tests/performance && locust -f locust_test.py --headless -u 100 -r 10 -t 60s

# Clean up
clean:
	@echo "🧹 Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	@echo "✅ Cleanup complete!"

# Initialize project structure
init-project:
	@echo "🏗️ Creating project structure..."
	mkdir -p api/{routers,models,services,telemetry,tests}
	mkdir -p solver/{tests}
	mkdir -p agents/{prompts,tests}
	mkdir -p k8s-operator/{crd,controllers}
	mkdir -p infra/{docker,k8s,wireguard,prometheus,grafana,otel}
	mkdir -p tests/{integration,performance,mocks}
	mkdir -p docs
	touch api/__init__.py
	touch solver/__init__.py
	touch agents/__init__.py
	@echo "✅ Project structure created!"

# Quick demo for investors
demo:
	@echo "🎯 Starting GridSynapse Demo..."
	docker-compose up -d
	@echo "⏳ Waiting for services to start..."
	sleep 10
	@echo "🚀 Running demo script..."
	python scripts/demo.py
	@echo "✅ Demo complete! Check http://localhost:8000/docs"

# Generate requirements files
requirements:
	@echo "📦 Generating requirements files..."
	cd api && pip freeze > requirements.txt
	cd solver && pip freeze > requirements.txt
	cd agents && pip freeze > requirements.txt

# Git hooks
install-hooks:
	@echo "🪝 Installing git hooks..."
	pre-commit install
	@echo "✅ Git hooks installed!"
