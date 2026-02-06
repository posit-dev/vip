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
    uv run ruff check src/ tests/

# Run ruff formatter check (fails if files would change)
format-check:
    uv run ruff format --check src/ tests/

# Auto-fix lint issues
lint-fix:
    uv run ruff check --fix src/ tests/

# Format code in place
format:
    uv run ruff format src/ tests/

# Run all checks (lint + format)
check: lint format-check

# Auto-fix everything (lint fixes + formatting)
fix: lint-fix format

# Run the full test suite
test *ARGS:
    uv run pytest {{ ARGS }}

# Run tests for a specific product (connect, workbench, package_manager)
test-product PRODUCT:
    uv run pytest -m {{ PRODUCT }}

# Run tests and generate the Quarto report data
report:
    uv run pytest --vip-report=report/results.json
    cd report && quarto render
