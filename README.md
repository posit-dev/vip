# VIP - Verified Installation of Posit

![VIP mascot](https://github.com/user-attachments/assets/f28c5cb5-701a-4491-99f9-102ff6fb6283)

An open-source, extensible test suite that validates Posit Team deployments are
installed correctly and functioning properly.

VIP uses **BDD-style tests** (pytest-bdd + Playwright) to verify Connect,
Workbench, and Package Manager.  Results are compiled into a **Quarto report**
that can be published to a Connect server.

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[just](https://just.systems/)** (optional, for running common tasks)

## Quick start

```bash
# Clone the repo
git clone https://github.com/posit-dev/vip.git
cd vip

# Set up with uv (recommended)
uv sync                          # install all dependencies
uv run playwright install chromium

# Or set up with pip
pip install -e ".[dev]"
playwright install chromium

# Configure
cp vip.toml.example vip.toml
# Edit vip.toml with your deployment details

# Set secrets via environment variables
export VIP_CONNECT_API_KEY="your-api-key"
export VIP_TEST_USERNAME="test-user"
export VIP_TEST_PASSWORD="test-password"

# Run all tests
uv run pytest              # with uv
pytest                     # with pip

# Run tests for a single product
uv run pytest -m connect
uv run pytest -m workbench
uv run pytest -m package_manager

# Generate the Quarto report
uv run pytest --vip-report=report/results.json
cd report && quarto render
```

## Configuration

Copy `vip.toml.example` to `vip.toml` and edit it for your deployment.  Each
product section can be disabled individually by setting `enabled = false`.

Secrets (API keys, passwords) should be set via environment variables rather
than stored in the configuration file:

| Variable | Purpose |
|---|---|
| `VIP_CONNECT_API_KEY` | Connect admin API key |
| `VIP_TEST_USERNAME` | Test user login name |
| `VIP_TEST_PASSWORD` | Test user login password |

You can also point to the config file explicitly:

```bash
pytest --vip-config=/path/to/vip.toml
```

## Test categories

| Category | Marker | Description |
|---|---|---|
| Prerequisites | `prerequisites` | Components installed, auth configured, admins onboarded |
| Package Manager | `package_manager` | CRAN/PyPI mirrors, repos, private packages |
| Connect | `connect` | Login, content deploy, data sources, packages, email, runtimes |
| Workbench | `workbench` | Login, IDE launch, sessions, packages, data sources, runtimes |
| Cross-product | `cross_product` | SSL, monitoring, system resources |
| Performance | `performance` | Load times, package install speed, concurrency, resource usage |
| Security | `security` | HTTPS enforcement, auth policy, secrets storage |

Run a specific category:

```bash
pytest -m connect
pytest -m "performance and connect"
```

## Version support

Tests can be pinned to product versions with the `min_version` marker:

```python
@pytest.mark.min_version(product="connect", version="2024.05.0")
def test_new_api_feature():
    ...
```

Tests that target a version newer than the deployment under test are
automatically skipped.

## Extensibility

Customers can add site-specific tests without modifying the VIP source tree.

1. Create a directory with `.feature` and `.py` files following the same
   conventions as the built-in tests.
2. Point VIP at it via configuration or the CLI:

```toml
# vip.toml
[general]
extension_dirs = ["/opt/vip-custom-tests"]
```

```bash
pytest --vip-extensions=/opt/vip-custom-tests
```

The custom tests directory is added to pytest's collection path at runtime.
See `examples/custom_tests/` for a working example.

## Quarto report

After running the tests, generate a report:

```bash
pytest --vip-report=report/results.json
cd report
quarto render
```

The rendered report can be published to Connect:

```bash
quarto publish connect --server https://connect.example.com
```

## Design principles

- **Non-destructive** - tests create, verify, and clean up their own content.
  They never modify or delete existing customer content.
- **Diagnostic** - tests are sequenced so failures localize problems.
  Prerequisites run first; product tests follow.
- **Loosely coupled** - the suite avoids tight coupling to product client
  libraries.  API calls use plain HTTP where practical.
- **Duplication over coupling** - code duplication with product-internal test
  suites is acceptable if it keeps VIP independent and version-flexible.

## Development

### Setup

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev tools like ruff)
uv sync

# Or with pip
pip install -e ".[dev]"
```

### Linting and formatting

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
uv run ruff check src/ tests/        # lint
uv run ruff format --check src/ tests/  # format check
uv run ruff check --fix src/ tests/  # auto-fix lint
uv run ruff format src/ tests/       # reformat
```

### Type checking

```bash
uv run mypy src/
```

## License

MIT - see [LICENSE](LICENSE).
