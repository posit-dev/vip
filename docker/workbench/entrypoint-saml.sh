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

# Provision the mock-IdP realm's test user (docker/keycloak/realm-vip.json)
# as a local Unix account. auth-saml only authenticates against Keycloak --
# rserver still has to resolve the asserted username to an OS account, and
# without one it rejects the session ("Error converting userIdentifier to
# username" / "Failed to get user details."). This image has no
# cont-init.d/s6-overlay to run docker/workbench/startup.sh for us the way
# compose.yml's password-auth stack does, so call the same script directly.
# It is installed as vip-create-test-user.sh, NOT startup.sh: the stock image
# already ships its own /usr/local/bin/startup.sh (the supervisord
# "rstudio-workbench" program runs it to create the rstudio user and exec
# rserver), and overwriting that stops rserver from ever starting.
# It shares the VIP_TEST_USERNAME/VIP_TEST_PASSWORD env contract (and
# defaults) with that stack.
#
# The script is idempotent, but `useradd -m` can still exit non-zero when the
# home directory already exists -- which happens on a container recreate
# against a warm /home volume, since /etc/passwd lives in the image layer and
# its own `id` check therefore misses. Tolerate that, then assert the
# postcondition, so a genuine provisioning failure stops the container here
# instead of resurfacing later as an unexplained sign-in rejection.
/usr/local/bin/vip-create-test-user.sh || true
if ! id "${VIP_TEST_USERNAME:-vip_test}" >/dev/null 2>&1; then
  echo "entrypoint-saml: ERROR: could not provision ${VIP_TEST_USERNAME:-vip_test}." >&2
  exit 1
fi

exec "$@"
