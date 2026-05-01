#!/usr/bin/env bash
# Build and run the RHEL headless Chromium smoke test for the given UBI version.
# Usage: ./scripts/rhel-smoke.sh <9|10>
set -euo pipefail

version="${1:-}"
case "$version" in
    9|10) ;;
    *) echo "Usage: $0 <9|10>" >&2; exit 2 ;;
esac

docker build --platform linux/amd64 \
    -f "docker/rhel${version}/Dockerfile" \
    -t "vip-rhel${version}-smoke" .
docker run --rm --platform linux/amd64 "vip-rhel${version}-smoke"

echo "==> verifying vip install --dry-run reports already up to date"
docker run --rm --platform linux/amd64 "vip-rhel${version}-smoke" \
    /bin/sh -c 'uv run vip install --dry-run | grep -q "already up to date"'

echo "==> verifying vip uninstall --yes runs cleanly"
docker run --rm --platform linux/amd64 "vip-rhel${version}-smoke" \
    /bin/sh -c 'uv run vip uninstall --yes | tee /tmp/uninst.log; \
                grep -q "vip uninstall: complete" /tmp/uninst.log'
