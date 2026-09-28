#!/bin/bash
set -euo pipefail
# Trust the mock-IdP E2E stack's shared CA before Connect starts, so its
# OIDC discovery fetch to https://keycloak.vip.test:8443/realms/vip succeeds.
# Runs as root (the image's normal startup path also does its own privilege
# handling in startup.sh). The stock image has no tini/init wrapper of its
# own (CMD runs startup.sh directly) so `exec` here is enough to keep signal
# handling equivalent to upstream.

if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/vip-mock-idp-ca.crt
  update-ca-certificates
else
  echo "entrypoint-oidc: WARNING: /certs/ca.crt not found; OIDC discovery will fail." >&2
fi

# The stock image's startup.sh activates via `license-manager activate
# $PCT_LICENSE` when PCT_LICENSE is set -- that command expects a short
# activation *key*, not a PEM license *file*'s contents. The CONNECT_LICENSE
# secret used across this repo's CI (connect-smoke.yml, connect-integration.yml,
# with-connect) is a license file, so passing it through PCT_LICENSE splats
# "-----BEGIN ..." onto the command line as bogus options and Connect exits 1.
# Write it to a file instead and point startup.sh at it via
# PCT_LICENSE_FILE_PATH, which takes the file-based license path instead of the
# CLI-arg activation path.
if [ -n "${PCT_LICENSE:-}" ]; then
  printf '%s' "${PCT_LICENSE}" > /etc/rstudio-connect/license.lic
  export PCT_LICENSE_FILE_PATH=/etc/rstudio-connect/license.lic
  unset PCT_LICENSE
fi

exec "$@"
