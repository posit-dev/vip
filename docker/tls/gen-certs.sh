#!/bin/sh
set -eu
# Generate a throwaway CA plus leaf certificates for the mock-IdP E2E stack.
#
# Keycloak, Connect, and Workbench all require an HTTPS issuer/redirect URI
# for OIDC (self-signed certs are rejected by both products' OIDC discovery
# clients), so every service in this stack terminates TLS with a cert signed
# by one shared CA. Test code and the browser under Playwright trust the same
# CA via VIP's existing `--ca-bundle` flag -- see auth.py's `ca_bundle`
# plumbing, which already exports `NODE_EXTRA_CA_CERTS` for Chromium.
#
# Output layout (under $OUT, a shared volume mounted by every service):
#   ca.crt                 -- the CA cert (trust this everywhere)
#   ca.key                 -- CA private key (throwaway; never used outside this stack)
#   keycloak.crt/.key      -- leaf cert for keycloak.vip.test
#   connect.crt/.key       -- leaf cert for connect.vip.test
#   workbench.crt/.key     -- leaf cert for workbench.vip.test
#
# Idempotent: skips generation if ca.crt already exists, so re-running
# `docker compose up` against a warm volume doesn't rotate certs underneath
# a running Keycloak/Connect/Workbench.

OUT="${OUT:-/certs}"
DOMAINS="keycloak connect workbench"

if [ -f "${OUT}/ca.crt" ]; then
  echo "gen-certs: ${OUT}/ca.crt already exists, skipping generation."
  exit 0
fi

mkdir -p "${OUT}"

echo "gen-certs: generating CA ..."
openssl req -x509 -newkey rsa:4096 -sha256 -days 30 -nodes \
  -keyout "${OUT}/ca.key" -out "${OUT}/ca.crt" \
  -subj "/CN=VIP Mock-IdP E2E CA"

for name in ${DOMAINS}; do
  domain="${name}.vip.test"
  echo "gen-certs: generating leaf cert for ${domain} ..."
  openssl req -newkey rsa:2048 -sha256 -nodes \
    -keyout "${OUT}/${name}.key" -out "${OUT}/${name}.csr" \
    -subj "/CN=${domain}"
  # -extfile needs a real file, not process substitution (<(...) is a
  # bashism and this script runs under /bin/sh, e.g. busybox ash in the
  # alpine/openssl cert-init container).
  extfile="${OUT}/${name}.extfile"
  printf "subjectAltName=DNS:%s" "${domain}" > "${extfile}"
  openssl x509 -req -sha256 -days 30 \
    -in "${OUT}/${name}.csr" \
    -CA "${OUT}/ca.crt" -CAkey "${OUT}/ca.key" -CAcreateserial \
    -out "${OUT}/${name}.crt" \
    -extfile "${extfile}"
  rm -f "${OUT}/${name}.csr" "${extfile}"
done

chmod 644 "${OUT}"/*.crt
chmod 644 "${OUT}"/*.key
echo "gen-certs: done."
