# Ubuntu 24.04 headless Chromium smoke test image.
#
# Also proves the #621 fix against a real Ubuntu 24.04 dpkg database: its
# 64-bit time_t transition renamed several Chromium runtime libs (libcups2,
# libatk1.0-0, libatk-bridge2.0-0, libglib2.0-0) to a t64 suffix, keeping the
# old names only as dpkg Provides entries -- see src/vip/install/packages.py.
# `vip install`'s first run apt-installs them under their old (requested)
# names, which apt resolves to the real t64 packages. The second `vip install
# --dry-run` below must then report nothing left to install; if detection
# regressed to matching only real package names, it would re-list all four
# and this build step fails instead of the loop going unnoticed.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# python3.12 is required by vip's pyproject.toml. procps provides ps.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 python3-pip procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (matches version pinned in vip's main Dockerfiles)
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

# Sync vip's Python dependencies. Frozen lockfile reproduces CI exactly.
RUN uv sync --frozen

# Refresh the apt index dropped above -- vip install's apt calls run in this
# later layer and need a live index, not just the packages already fetched.
RUN apt-get update

# Install Chromium runtime libs (via apt) and the Playwright browser bundle via
# vip. Runs as root inside Docker, so vip install invokes apt directly, which
# resolves libcups2/libatk1.0-0/libatk-bridge2.0-0/libglib2.0-0 to their real
# t64 packages under the hood.
RUN uv run vip install

# Prove #621's detection fix against real dpkg-query output: querying each of
# the four renamed packages by its old (requested) name must now count as
# installed, so a second `vip install --dry-run` sees nothing left to do
# instead of re-demanding the same packages forever.
RUN uv run vip install --dry-run | tee /tmp/dry-run.log \
    && grep -q "nothing to install" /tmp/dry-run.log

CMD ["uv", "run", "python", "/app/docker/playwright-smoke.py"]
