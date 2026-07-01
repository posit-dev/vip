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

# The stock image's startup.sh activates via `license-manager activate
# $RSC_LICENSE` when RSC_LICENSE is set -- that command expects a short
# activation *key*, not a PEM license *file*'s contents. The CONNECT_LICENSE
# secret used across this repo's CI (connect-smoke.yml, connect-integration.yml,
# with-connect) is a license file, so passing it through RSC_LICENSE splats
# "-----BEGIN ..." onto the command line as bogus options and Connect exits 1.
# Write it to a file instead and point startup.sh at it via
# RSC_LICENSE_FILE_PATH, which takes the file-based activate-file path.
if [ -n "${RSC_LICENSE:-}" ]; then
  printf '%s' "${RSC_LICENSE}" > /etc/rstudio-connect/license.lic
  export RSC_LICENSE_FILE_PATH=/etc/rstudio-connect/license.lic
  unset RSC_LICENSE
fi

exec tini -- "$@"
