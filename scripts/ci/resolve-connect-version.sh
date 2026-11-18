#!/usr/bin/env bash
# Resolve the running Connect version from /__api__/server_settings and write it to
# $GITHUB_OUTPUT as `resolved=<version>`.
#
# Retries for up to two minutes because Connect can accept the container start before its API
# answers. Reads VIP_CONNECT_API_KEY and CONNECT_SERVER from the environment, so the key never
# appears on a command line or in a template expansion.
set -euo pipefail

RESOLVED=0
for i in $(seq 1 60); do
  RESPONSE=$(curl -sf --connect-timeout 5 --max-time 15 \
    -H "Authorization: Key ${VIP_CONNECT_API_KEY}" \
    "${CONNECT_SERVER}/__api__/server_settings") && { RESOLVED=1; break; }
  if [ "${i}" -lt 60 ]; then
    echo "Attempt ${i}: server_settings not reachable yet, retrying..."
    sleep 2
  fi
done
if [ "${RESOLVED}" != "1" ]; then
  echo "ERROR: server_settings did not become reachable after 60 attempts"
  exit 1
fi
echo "server_settings reachable (attempt ${i})"
VERSION=$(echo "${RESPONSE}" | jq -r '.version')
if [ -z "${VERSION}" ] || [ "${VERSION}" = "null" ]; then
  echo "ERROR: Could not resolve Connect version from server_settings"
  echo "Response body: ${RESPONSE}"
  exit 1
fi
echo "Resolved Connect version: ${VERSION}"
echo "resolved=${VERSION}" >> "$GITHUB_OUTPUT"
