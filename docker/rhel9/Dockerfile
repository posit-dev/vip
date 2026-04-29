# RHEL 9 headless Chromium smoke test image
# See docs/rhel.md and docs/superpowers/specs/2026-04-29-rhel9-headless-smoke-design.md
FROM redhat/ubi9

# Chromium runtime dependencies for the Ubuntu 24.04 fallback build,
# translated to RHEL 9 package names. Union of the official Playwright
# ubuntu24.04-x64 chromium dep group and the empirical list from
# posit-dev/vip#227. python3.12 is required by vip's pyproject.toml.
RUN dnf install -y \
        nss nspr atk at-spi2-atk at-spi2-core cups-libs dbus-libs libdrm \
        mesa-libgbm glib2 pango cairo libX11 libxcb libXcomposite libXdamage \
        libXext libXfixes libxkbcommon libXrandr libXtst libxshmfence alsa-lib \
        python3.12 python3.12-pip procps-ng \
    && dnf clean all

# Install uv (matches version pinned in vip's main Dockerfile)
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

# Sync vip's Python dependencies. Frozen lockfile reproduces CI exactly.
RUN uv sync --frozen

# Download the Playwright Chromium fallback build for ubuntu24.04-x64.
# Deliberately NO --with-deps: that hardcodes apt-get and fails on RHEL.
# A "BEWARE: your OS is not officially supported" warning here is expected.
RUN uv run playwright install chromium

CMD ["uv", "run", "python", "/app/docker/rhel-smoke.py"]
