#!/bin/bash
set -euo pipefail
# Trust the mock-IdP E2E stack's shared CA before Connect starts, so its
# OIDC discovery fetch to https://keycloak.vip.test:8443/realms/vip succeeds.
# Runs as root (the image's normal startup path also does its own privilege
# handling in startup.sh); tini + startup.sh are exec'd afterward so signals
# still propagate correctly.

if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/vip-mock-idp-ca.crt
  update-ca-certificates
else
  echo "entrypoint-oidc: WARNING: /certs/ca.crt not found; OIDC discovery will fail." >&2
fi

exec tini -- "$@"
