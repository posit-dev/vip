# openSUSE Leap headless Chromium smoke test image
FROM opensuse/leap:15

# python312 is required by vip's pyproject.toml. procps provides ps.
# gzip and tar are needed for the uv tarball extraction in the COPY --from below.
RUN zypper -n install \
        python312 python312-pip procps gzip tar \
    && zypper clean --all

# Install uv (matches version pinned in vip's main Dockerfiles)
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

# Sync vip's Python dependencies. Frozen lockfile reproduces CI exactly.
RUN uv sync --frozen

# Install Chromium runtime libs (via zypper) and the Playwright browser bundle via vip.
# Runs as root inside Docker, so vip install invokes zypper directly.
RUN uv run vip install

CMD ["uv", "run", "python", "/app/docker/playwright-smoke.py"]
