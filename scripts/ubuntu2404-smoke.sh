#!/usr/bin/env bash
# Build and run the Ubuntu 24.04 headless Chromium smoke test.
#
# Also proves the #621 detection fix: the image's own build already runs
# `vip install` then `vip install --dry-run` and fails the build if any of
# the four t64-renamed packages get re-demanded (see docker/ubuntu2404/
# Dockerfile). This script re-checks the same dry-run output after the build
# for a clear local-dev signal, matching the rhel/opensuse-leap smoke scripts'
# shape. Scoped to the detection fix, not a full vip-install integration
# test, so unlike those scripts this one does not also exercise `vip
# uninstall`.
set -euo pipefail

docker build --platform linux/amd64 \
    -f "docker/ubuntu2404/Dockerfile" \
    -t "vip-ubuntu2404-smoke" .
docker run --rm --platform linux/amd64 "vip-ubuntu2404-smoke"

echo "==> verifying vip install --dry-run reports nothing to install"
docker run --rm --platform linux/amd64 "vip-ubuntu2404-smoke" \
    bash -c 'set -eo pipefail; uv run vip install --dry-run | grep -q "nothing to install"'
