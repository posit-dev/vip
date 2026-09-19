#!/bin/bash
set -euo pipefail
# Create a test user for VIP on first boot.
#
# Only the OIDC and SAML lanes use this. They COPY it to
# /usr/local/bin/vip-create-test-user.sh and call it from their own entrypoint,
# because they need the OS account to exist before rserver starts and the image
# has no cont-init.d/s6 pre-start hook. It must exit cleanly rather than exec
# anything, because the caller execs the real entrypoint afterwards.
#
# compose.yml does NOT use this: the password-auth stack sets the image's own
# PWB_TESTUSER/PWB_TESTUSER_PASSWD instead, which /usr/local/bin/startup.sh in
# the image acts on. Prefer that interface for any new caller that can wait
# until supervisord starts.
#
# Exiting non-zero stops the whole container, because both callers treat a
# failed postcondition as fatal. The risky path is a recreate against a warm /home
# volume -- /etc/passwd lives in the image layer and resets while /home
# survives, so the `id` check below misses and `useradd -m` runs over an
# existing home directory. On Ubuntu 24.04 that only warns and exits 0
# (measured), but entrypoint-oidc.sh reports having seen it exit non-zero, so
# tolerate it and assert the postcondition rather than trusting the exit code
# either way. A real provisioning failure then stops the caller here instead
# of resurfacing later as an unexplained sign-in rejection.

VIP_USER="${VIP_TEST_USERNAME:-vip_test}"
VIP_PASS="${VIP_TEST_PASSWORD:-vip_test_password}"

if ! id "$VIP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$VIP_USER" || true
fi

if ! id "$VIP_USER" &>/dev/null; then
    echo "VIP: ERROR: could not provision test user '${VIP_USER}'." >&2
    exit 1
fi

# Set the password every time, not just on creation: a warm-volume recreate
# can carry an account provisioned under a different VIP_TEST_PASSWORD.
echo "${VIP_USER}:${VIP_PASS}" | chpasswd
echo "VIP: test user '${VIP_USER}' ready"
