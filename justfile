# VIP - Verified Installation of Posit

# Exact uv version used to regenerate uv.lock. Must satisfy the
# `required-version` floor in pyproject.toml's [tool.uv]. Bump both together.
UV_VERSION := "0.11.28"

# List available recipes
default:
    @just --list

# Install all dependencies (system packages where possible, plus Playwright)
setup:
    uv sync
    uv run vip install

# Same as `setup` — kept for muscle memory; vip install handles RHEL detection.
setup-rhel: setup

# Regenerate uv.lock with the pinned uv version (see UV_VERSION above).
# Use this instead of a bare `uv lock` so the lockfile is byte-reproducible
# regardless of the uv installed locally — `uvx` fetches the exact pin. This is
# also how you resolve a uv.lock merge conflict: take either side, then relock.
#   git checkout --theirs uv.lock && just relock
relock:
    uvx --from uv=={{ UV_VERSION }} uv lock

# Run ruff linter
lint:
    uv run ruff check src/ selftests/ examples/ docker/

# Run ruff formatter check (fails if files would change)
format-check:
    uv run ruff format --check src/ selftests/ examples/ docker/

# Auto-fix lint issues
lint-fix:
    uv run ruff check --fix src/ selftests/ examples/ docker/

# Format code in place
format:
    uv run ruff format src/ selftests/ examples/ docker/

# Run all checks (lint + format)
check: lint format-check

# Auto-fix everything (lint fixes + formatting)
fix: lint-fix format

# Run mypy type checker
typecheck:
    uv run mypy src/vip/

# Run selftests with coverage
coverage:
    uv run pytest selftests/ --cov=src/vip --cov-report=term-missing

# Run selftests (no products required)
selftest *ARGS:
    uv run pytest selftests/ {{ ARGS }}

# Run the full VIP test suite against configured products
test *ARGS:
    uv run pytest tests/ {{ ARGS }}

# Run tests for a specific product (connect, workbench, package_manager)
test-product PRODUCT:
    uv run pytest tests/ -m {{ PRODUCT }}

# Generate the Quarto report from product test results
report *ARGS:
    uv run pytest tests/ {{ ARGS }}
    cd report && uv run quarto render

# Create a new showboat demo document
demo-init TITLE:
    uvx showboat init demo.md "{{ TITLE }}"

# Verify an existing demo document
demo-verify:
    uvx showboat verify demo.md

# Verify and move demo.md to validation_docs/ with a descriptive name
demo-save NAME:
    uvx showboat verify demo.md
    mv demo.md validation_docs/demo-{{ NAME }}.md
    @echo "Saved to validation_docs/demo-{{ NAME }}.md"

# Generate test catalog and feature matrix JSON for the website
website-data:
    uv run python scripts/generate-test-catalog.py
    uv run python scripts/generate-feature-matrix.py

# Start the local docker-compose dev environment
compose-up *SERVICES:
    docker compose up -d --wait {{ SERVICES }}
    @docker compose ps

# Stop the local docker-compose dev environment
compose-down:
    docker compose down

# Run VIP tests against the local docker-compose environment (Workbench only by default)
test-local *ARGS:
    docker compose up -d --wait
    uv run vip verify --config vip.toml.local --categories workbench {{ ARGS }}

# Run VIP tests against the full local stack (requires RSC_LICENSE and RSPM_LICENSE).
# Passes URL flags directly so Connect and PM don't need to be enabled in vip.toml.local.
test-local-full *ARGS:
    docker compose --profile full up -d --wait
    uv run vip verify --connect-url http://localhost:3939 --workbench-url http://localhost:8787 --package-manager-url http://localhost:4242 {{ ARGS }}

# Generate a Quarto report from selftests (for CI / demo purposes)
report-selftest:
    uv run pytest selftests/
    cd report && uv run quarto render

# Start the mock-IdP E2E stack (Keycloak + Connect + Workbench, real OIDC).
# Requires RSC_LICENSE and RSW_LICENSE. Add vip.test hostnames to /etc/hosts
# first: `127.0.0.1 keycloak.vip.test connect.vip.test workbench.vip.test`.
mock-idp-up:
    docker compose -f compose.mock-idp.yml up -d --build --wait
    @docker compose -f compose.mock-idp.yml ps

# Stop the mock-IdP E2E stack and remove its volumes (certs, realm state, home dirs)
mock-idp-down:
    docker compose -f compose.mock-idp.yml down -v

# Print the mock-IdP stack's auto-generated TOTP seed. Export it before
# running `vip verify --headless-auth` locally:
#   export VIP_TEST_TOTP_SECRET=$(just mock-idp-totp-secret)
mock-idp-totp-secret:
    @docker run --rm -v vip-mock-idp_mock-idp-certs:/certs:ro alpine/openssl:3.5.4 cat /certs/totp-secret.b32

# Build and run the RHEL 9 headless Chromium smoke test
rhel9-smoke:
    ./scripts/rhel-smoke.sh 9

# Build and run the RHEL 10 headless Chromium smoke test
rhel10-smoke:
    ./scripts/rhel-smoke.sh 10

# Build and run the openSUSE Leap headless Chromium smoke test
opensuse-leap-smoke:
    ./scripts/opensuse-leap-smoke.sh
