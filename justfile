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
    uv run pytest tests/ --vip-report=report/results.json {{ ARGS }}
    cd report && uv run quarto render

# Create a new showboat demo document
demo-init TITLE:
    uvx showboat init demo.md "{{ TITLE }}"

# Verify an existing demo document
demo-verify:
    uvx showboat verify demo.md

# Generate a Quarto report from selftests (for CI / demo purposes)
report-selftest:
    uv run pytest selftests/ --vip-report=report/results.json
    cd report && uv run quarto render
