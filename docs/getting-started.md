# Getting Started

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[just](https://just.systems/)** (optional, for running common tasks)

## Installation

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
```

## Quick start

```bash
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

# Generate the Quarto report (results.json is written by default)
uv run pytest
cd report && quarto render
```

For a graphical interface, see the [Shiny App](shiny-app.md) guide —
it lets you select categories, run tests, and view reports from your
browser or the Workbench Viewer pane.

See [Configuration](configuration.md) for details on `vip.toml` and
environment variables, and [Authentication](authentication.md) for
identity provider setup.
