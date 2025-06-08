# GridSynapse MVP - Development Makefile
# Quick commands for development and deployment

.PHONY: help install dev test clean docker-up docker-down deploy-local docs

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