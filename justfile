# VIP - Verified Installation of Posit

# List available recipes
default:
    @just --list

# Install all dependencies with uv
setup:
    uv sync
    uv run playwright install chromium

# Run ruff linter
lint:
    uv run ruff check src/ tests/ selftests/ examples/

# Run ruff formatter check (fails if files would change)
format-check:
    uv run ruff format --check src/ tests/ selftests/ examples/

# Auto-fix lint issues
lint-fix:
    uv run ruff check --fix src/ tests/ selftests/ examples/

# Format code in place
format:
    uv run ruff format src/ tests/ selftests/ examples/

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

# Run VIP tests against the full local stack (requires RSC_LICENSE and RSPM_LICENSE)
test-local-full *ARGS:
    docker compose --profile full up -d --wait
    uv run vip verify --config vip.toml.local {{ ARGS }}

# Generate a Quarto report from selftests (for CI / demo purposes)
report-selftest:
    uv run pytest selftests/
    cd report && uv run quarto render
