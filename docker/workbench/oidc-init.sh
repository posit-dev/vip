#!/bin/bash
set -euo pipefail
# Configure Workbench for OIDC against the mock-IdP E2E Keycloak realm.
# Runs as a cont-init.d script (see compose.mock-idp.yml), same mechanism as
# startup.sh's test-user creation -- both mount into /etc/cont-init.d/.

if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/vip-mock-idp-ca.crt
  update-ca-certificates
else
  echo "oidc-init: WARNING: /certs/ca.crt not found; OIDC discovery will fail." >&2
fi

cat > /etc/rstudio/rserver.conf << 'EOF'
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
