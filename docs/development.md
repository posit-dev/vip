# Development

## Setup

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev tools like ruff)
uv sync

# Or with pip
pip install -e ".[dev]"
```

## Linting and formatting

VIP uses [ruff](https://docs.astral.sh/ruff/) for both linting and code
formatting.  The easiest way to run checks is with [just](https://just.systems/):

```bash
just check          # run both lint and format checks
just fix            # auto-fix lint issues and reformat

# Or individually
just lint           # ruff check
just format-check   # ruff format --check
just lint-fix       # ruff check --fix
just format         # ruff format
```

Without just, run ruff directly:

```bash
uv run ruff check src/ src/vip_tests/        # lint
uv run ruff format --check src/ src/vip_tests/  # format check
uv run ruff check --fix src/ src/vip_tests/  # auto-fix lint
uv run ruff format src/ src/vip_tests/       # reformat
```

## Type checking

```bash
uv run mypy src/
```

## Design principles

- **Non-destructive** — tests create, verify, and clean up their own content.
  They never modify or delete existing customer content.
- **Diagnostic** — tests are sequenced so failures localize problems.
  Prerequisites run first; product tests follow.
- **Loosely coupled** — the suite avoids tight coupling to product client
  libraries.  API calls use plain HTTP where practical.
- **Duplication over coupling** — code duplication with product-internal test
  suites is acceptable if it keeps VIP independent and version-flexible.
