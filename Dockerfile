# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies (needed for some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY sandwich_bot/ ./sandwich_bot/
COPY static/ ./static/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY pyproject.toml .

# Create directory for SQLite database
RUN mkdir -p /app/data

# Default database location (can be overridden with environment variable)
ENV DATABASE_URL=sqlite:///./app.db

# Expose the port the app runs on
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/health')" || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "sandwich_bot.main:app", "--host", "0.0.0.0", "--port", "8004"]
