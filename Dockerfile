FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_PORT=8800 \
    DEVICE_PORT=5000 \
    HOST=0.0.0.0

WORKDIR /app

# Install basic system packages needed for container healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies first to take advantage of layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Expose both Web Dashboard (8800) and famX Hardware Gateway (5000)
EXPOSE 8800 5000

# Health check to ensure server responds
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8800/check_auth || exit 1

# Launch dual-port application
CMD ["python", "app.py"]
