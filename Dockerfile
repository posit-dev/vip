# VIP - Verified Installation of Posit
# Container image for running VIP tests as Kubernetes Jobs
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (without the project itself yet)
RUN uv sync --frozen --no-install-project

# Copy the full project
COPY . .

# Install the project itself
RUN uv sync --frozen

# Install playwright browsers (chromium is already in the base image, but ensure deps)
RUN uv run playwright install --with-deps chromium

# Default entrypoint runs pytest
# Config file should be mounted at /app/vip.toml
ENTRYPOINT ["uv", "run", "pytest"]

# Default args: run all tests with short tracebacks and verbose output
CMD ["--tb=short", "-v"]
