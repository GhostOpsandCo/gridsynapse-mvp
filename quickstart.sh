#!/bin/bash
# GridSynapse MVP - Quick Start Script
# One command to impress investors: ./quickstart.sh

set -e

echo "
  ██████╗ ██████╗ ██╗██████╗ ███████╗██╗   ██╗███╗   ██╗ █████╗ ██████╗ ███████╗███████╗
 ██╔════╝ ██╔══██╗██║██╔══██╗██╔════╝╚██╗ ██╔╝████╗  ██║██╔══██╗██╔══██╗██╔════╝██╔════╝
 ██║  ███╗██████╔╝██║██║  ██║███████╗ ╚████╔╝ ██╔██╗ ██║███████║██████╔╝███████╗█████╗  
 ██║   ██║██╔══██╗██║██║  ██║╚════██║  ╚██╔╝  ██║╚██╗██║██╔══██║██╔═══╝ ╚════██║██╔══╝  
 ╚██████╔╝██║  ██║██║██████╔╝███████║   ██║   ██║ ╚████║██║  ██║██║     ███████║███████╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚══════╝╚══════╝
  
  🇺🇸 The Nervous System for America's AI Revolution 🇺🇸
"

# Check prerequisites
echo "🔍 Checking prerequisites..."

check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "❌ $1 is not installed. Please install it first."
        exit 1
    fi
}

check_command docker
check_command docker-compose
check_command git

echo "✅ All prerequisites installed!"

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ docker-compose.yml not found. Please run this script from the GridSynapse project root."
    exit 1
fi

# Create necessary directories
echo "🏗️ Setting up project structure..."
make init-project

# Create minimal requirements files if they don't exist
if [ ! -f "api/requirements.txt" ]; then
    echo "📝 Creating requirements files..."
    cat > api/requirements.txt << EOF
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
sqlalchemy==2.0.23
asyncpg==0.29.0
redis==5.0.1
httpx==0.25.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
opentelemetry-api==1.21.0
opentelemetry-sdk==1.21.0
opentelemetry-instrumentation-fastapi==0.42b0
prometheus-client==0.19.0
stripe==7.8.0
ortools==9.8.3296
EOF

    cat > solver/requirements.txt << EOF
ortools==9.8.3296
numpy==1.26.2
pandas==2.1.4
redis==5.0.1
pydantic==2.5.0
EOF

    cat > agents/requirements.txt << EOF
openai==1.6.1
langchain==0.0.350
pydantic==2.5.0
redis==5.0.1
httpx==0.25.2
EOF
fi

# Create API Dockerfile if it doesn't exist
if [ ! -f "api/Dockerfile" ]; then
    echo "🐳 Creating Dockerfiles..."
    cat > api/Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

    cat > solver/Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "optimizer.py"]
EOF
fi

# Create .env file with defaults
if [ ! -f ".env" ]; then
    echo "🔑 Creating environment configuration..."
    cat > .env << EOF
# GridSynapse Environment Variables
ENVIRONMENT=development
JWT_SECRET_KEY=super-secret-key-change-in-production
WATTTIME_API_KEY=demo-key
STRIPE_SECRET_KEY=sk_test_demo
DATABASE_URL=postgresql://gridsynapse:gridsynapse@postgres:5432/gridsynapse
REDIS_URL=redis://redis:6379
EOF
fi

# Start services
echo "🚀 Starting GridSynapse services..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to initialize..."
sleep 15

# Check if API is responding
echo "🔍 Checking API health..."
until curl -f http://localhost:8000/api/v1/health > /dev/null 2>&1; do
    echo "Waiting for API to be ready..."
    sleep 2
done

echo "
✅ GridSynapse MVP is running!

🌐 Services:
   - API Documentation: http://localhost:8000/docs
   - Prometheus Metrics: http://localhost:9090
   - Grafana Dashboards: http://localhost:3000 (admin/admin)

🚀 Quick Demo:
   1. Open http://localhost:8000/docs in your browser
   2. Try the /api/v1/health endpoint
   3. Submit a test job via /api/v1/jobs
   4. Check pricing forecasts at /api/v1/prices

💡 Useful commands:
   - View logs: docker-compose logs -f
   - Stop services: docker-compose down
   - Run tests: make test
   - See all commands: make help

🇺🇸 GridSynapse - Powering America's AI Future! 🇺🇸
"

# Open browser if possible
if command -v open &> /dev/null; then
    open http://localhost:8000/docs
elif command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:8000/docs
fi