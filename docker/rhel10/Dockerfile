# RHEL 10 headless Chromium smoke test image
# See docs/rhel.md and docs/superpowers/specs/2026-04-29-rhel9-headless-smoke-design.md
FROM redhat/ubi10

# python3.12 is required by vip's pyproject.toml. procps-ng provides ps.
RUN dnf install -y \
        python3.12 python3.12-pip procps-ng \
    && dnf clean all

# Install uv (matches version pinned in vip's main Dockerfile)
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

# Sync vip's Python dependencies. Frozen lockfile reproduces CI exactly.
RUN uv sync --frozen

# Install Chromium runtime libs and the Playwright browser bundle via vip.
# Runs as root inside Docker, so vip install invokes dnf directly.
RUN uv run vip install

CMD ["uv", "run", "python", "/app/docker/rhel-smoke.py"]
