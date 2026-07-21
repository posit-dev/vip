# VIP - Verified Installation of Posit
# Container image for running VIP tests
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (without the project itself yet)
RUN uv sync --frozen --no-install-project

# Copy the full project
COPY . .

# Install the project itself
RUN uv sync --frozen

# Install playwright browsers + system deps (chromium is already in the base image, but ensure deps)
RUN uv run vip install

# Run as the existing non-root user from the base image (ubuntu, UID 1000)
RUN chown -R ubuntu:ubuntu /app
USER ubuntu
# Default entrypoint is the vip CLI; default subcommand is verify.
# Config file should be mounted at /app/vip.toml
ENTRYPOINT ["uv", "run", "vip"]

# Default args: run verify. Override to reach other subcommands, e.g.
#   docker run <img> status --json
#   docker run <img> --ci
CMD ["verify"]
