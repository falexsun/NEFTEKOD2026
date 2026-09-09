# Python base image
FROM python:3.11-slim

WORKDIR /app

# Install uv for fast package management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Create directories for data and models
RUN mkdir -p data models reports

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Default command: run API
CMD ["uv", "run", "uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
