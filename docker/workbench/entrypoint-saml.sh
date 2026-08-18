#!/bin/bash
set -euo pipefail
# Configure Workbench for SAML against the mock-IdP E2E Keycloak realm, then
# hand off to the stock image's own entrypoint (supervisord).
#
# The stock image has no cont-init.d/s6 pre-start hook -- it runs supervisord
# directly (see Dockerfile.saml) -- so this overrides ENTRYPOINT the same way
# entrypoint-oidc.sh does for the OIDC lane.
#
# SAML is exclusive of PAM/OIDC on a single Workbench instance, so this lane
# runs in its own container (see Dockerfile.saml) rather than toggling the
# existing OIDC one.

if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/vip-mock-idp-ca.crt
  update-ca-certificates
else
  echo "entrypoint-saml: WARNING: /certs/ca.crt not found; SAML metadata fetch will fail." >&2
fi

# Append -- the stock rserver.conf already carries launcher/admin/health-check
# settings (launcher-address, launcher-port, etc.) that a `>` overwrite would
# silently drop, breaking the session launcher.
# Confirmed against `rserver --help` on this image -- the cert options are
# `ssl-certificate` / `ssl-certificate-key`, not the `-file`-suffixed names
# used elsewhere (e.g. Connect's [HTTPS] Certificate/Key gcfg keys).
#
# No auth-saml-sp-* signing/encryption options are set: Workbench's SAML SSO
# docs (docs.posit.co/ide/server-pro/admin/authenticating_users/saml_sso.html)
# say request signing is "not required or even supported" in most setups, and
# the Keycloak client (docker/keycloak/realm-vip.json) sets
# "saml.client.signature": "false" to match -- it does not require a signed
# AuthnRequest from this SP. The SP entity ID and ACS URL are not configured
# here either: Workbench derives both from the incoming request's Host header
# plus ssl-enabled (there is no auth-saml option to set the entity ID
# explicitly), so they fall out of ssl-enabled=1 and this container being
# reached only at https://workbench-saml.vip.test:8788 -- matching the
# Keycloak client's clientId (SP entity ID/metadata URL) and redirectUris
# (ACS URL) below.
cat >> /etc/rstudio/rserver.conf << 'EOF'
ssl-enabled=1
ssl-certificate=/certs/workbench-saml.crt
ssl-certificate-key=/certs/workbench-saml.key
auth-saml=1
auth-saml-metadata-url=https://keycloak.vip.test:8443/realms/vip/protocol/saml/descriptor
auth-saml-sp-attribute-username=Username
EOF

# SAML does not use a client secret file -- unlike auth-openid, there is no
# openid-client-secret equivalent to write.

exec "$@"
