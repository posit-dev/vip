#!/usr/bin/env bash
# Build and run the Ubuntu 24.04 headless Chromium smoke test.
#
# Also proves the #621 fixes: the image's own build runs `vip install`, then
# fails the build if a second `vip install --dry-run` re-demands any of the
# four t64-renamed packages, or if the manifest recorded the requested alias
# rather than the t64 package apt actually installed (see docker/ubuntu2404/
# Dockerfile). This script re-checks both after the build for a clear
# local-dev signal, matching the rhel/opensuse-leap smoke scripts' shape.
# Scoped to those two fixes, not a full vip-install integration test, so
# unlike those scripts this one does not run `vip uninstall` itself -- it
# asserts on the manifest that drives it.
set -euo pipefail

docker build --platform linux/amd64 \
    -f "docker/ubuntu2404/Dockerfile" \
    -t "vip-ubuntu2404-smoke" .
docker run --rm --platform linux/amd64 "vip-ubuntu2404-smoke"

echo "==> verifying vip install --dry-run reports nothing to install"
docker run --rm --platform linux/amd64 "vip-ubuntu2404-smoke" \
    bash -c 'set -eo pipefail; uv run vip install --dry-run | grep -q "nothing to install"'

echo "==> verifying the manifest records removable t64 names, not aliases"
docker run --rm --platform linux/amd64 "vip-ubuntu2404-smoke" \
    python3 -c "import json; names = {i['name'] for i in json.load(open('/app/.vip-install.json'))['items'] if i.get('manager') == 'apt'}; assert 'libcups2t64' in names and 'libcups2' not in names, sorted(names)"
