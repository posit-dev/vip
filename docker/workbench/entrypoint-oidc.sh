#!/bin/bash
set -euo pipefail
# Configure Workbench for OIDC against the mock-IdP E2E Keycloak realm, then
# hand off to the stock image's own entrypoint (supervisord).
#
# The stock image has no cont-init.d/s6 pre-start hook -- it runs supervisord
# directly (see Dockerfile.oidc) -- so this overrides ENTRYPOINT the same way
# docker/connect/entrypoint-oidc.sh does for Connect.

if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/vip-mock-idp-ca.crt
  update-ca-certificates
else
  echo "entrypoint-oidc: WARNING: /certs/ca.crt not found; OIDC discovery will fail." >&2
fi

# Append -- the stock rserver.conf already carries launcher/admin/health-check
# settings (launcher-address, launcher-port, etc.) that a `>` overwrite would
# silently drop, breaking the session launcher.
cat >> /etc/rstudio/rserver.conf << 'EOF'
ssl-enabled=1
ssl-certificate-file=/certs/workbench.crt
ssl-certificate-key-file=/certs/workbench.key
auth-openid=1
auth-openid-issuer=https://keycloak.vip.test:8443/realms/vip
auth-openid-username-claim=preferred_username
EOF

cat > /etc/rstudio/openid-client-secret << 'EOF'
client-id=vip-workbench
client-secret=vip-workbench-secret
EOF
chmod 0600 /etc/rstudio/openid-client-secret

exec "$@"
