#!/bin/bash
# Create a test user for VIP on first boot.
# This script runs as a cont-init.d script inside the Workbench container.

VIP_USER="${VIP_TEST_USERNAME:-vip_test}"
VIP_PASS="${VIP_TEST_PASSWORD:-vip_test_password}"

# Only create the user if it doesn't already exist
if ! id "$VIP_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$VIP_USER"
    echo "${VIP_USER}:${VIP_PASS}" | chpasswd
    echo "VIP: Created test user '${VIP_USER}'"
else
    echo "VIP: Test user '${VIP_USER}' already exists"
fi
