#!/usr/bin/env bash
# Build and run the openSUSE Leap headless Chromium smoke test.
# Usage: ./scripts/opensuse-leap-smoke.sh
set -euo pipefail

docker build --platform linux/amd64 \
    -f "docker/opensuse-leap/Dockerfile" \
    -t "vip-opensuse-leap-smoke" .
docker run --rm --platform linux/amd64 "vip-opensuse-leap-smoke"

echo "==> verifying vip install --dry-run reports nothing to install"
docker run --rm --platform linux/amd64 "vip-opensuse-leap-smoke" \
    bash -c 'set -eo pipefail; uv run vip install --dry-run | grep -q "nothing to install"'

echo "==> verifying vip uninstall --yes runs cleanly"
docker run --rm --platform linux/amd64 "vip-opensuse-leap-smoke" \
    bash -c 'set -eo pipefail
             uv run vip uninstall --yes | tee /tmp/uninst.log
             grep -q "vip uninstall: complete" /tmp/uninst.log'
