#!/usr/bin/env bash
# Wait up to 120 seconds for the `packagemanager` container to answer its status endpoint.
# Prints the container logs and exits 1 if it never does.
set -euo pipefail

echo "Waiting for Package Manager to start..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:4242/__api__/status > /dev/null 2>&1; then
    echo "Package Manager is ready (attempt ${i})"
    exit 0
  fi
  sleep 2
done
echo "Package Manager failed to start within 120 seconds"
docker logs packagemanager
exit 1
