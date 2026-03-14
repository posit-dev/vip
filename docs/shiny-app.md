# Shiny App (Graphical Test Runner)

VIP includes a Shiny for Python app that provides a point-and-click
interface for running tests and viewing reports.  It is designed to
work inside a Posit Workbench session where the app opens directly in
the IDE's Viewer pane.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start in RStudio or Positron

1. **Open a terminal** in your IDE (Terminal tab in RStudio, or
   `Ctrl+`` ` in Positron).

2. **Clone and install VIP:**

   ```bash
   git clone https://github.com/posit-dev/vip.git
   cd vip
   uv sync
   uv run playwright install chromium
   ```

3. **Configure credentials** (skip this step if you will use URL
   overrides in the app):

   ```bash
   cp vip.toml.example vip.toml
   # Edit vip.toml with your deployment URLs and credentials,
   # or set environment variables:
   export VIP_CONNECT_API_KEY="your-api-key"
   export VIP_TEST_USERNAME="test-user"
   export VIP_TEST_PASSWORD="test-password"
   ```

4. **Launch the app:**

   ```bash
   uv run vip app
   ```

   The app opens in your default browser. Inside Workbench, it opens
   in the Viewer pane automatically.

## Using the app

### Sidebar controls

- **Config file path** — path to `vip.toml`.  Defaults to `./vip.toml`
  or the `VIP_CONFIG` environment variable.
- **Product URL overrides** (expand the accordion) — enter Connect,
  Workbench, or Package Manager URLs to run without a config file.
- **Test categories** — check the categories you want to run.  Use the
  Select all / Deselect all links for convenience.
- **Extra pytest args** — pass additional flags to pytest
  (e.g., `-x` to stop on first failure, `-k 'login'` to filter tests).
- **Run Tests** — start the test run.
- **Stop** — terminate a running test.

### Main panel tabs

| Tab | Description |
|-----|-------------|
| **Test Output** | Live-streaming terminal output from pytest.  A status badge shows Idle, Running, Passed, or Failed. |
| **Report** | Styled HTML report with summary metrics, results by category, expandable tracebacks, and troubleshooting hints.  Automatically updates when a test run completes. |

## CLI options

```
vip app [--config PATH] [--host HOST] [--port PORT] [--no-browser]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | `vip.toml` | Path to `vip.toml` (sets default in the app) |
| `--host` | `127.0.0.1` | Host to bind |
| `--port` | auto | Port number (0 = pick a free port) |
| `--no-browser` | off | Don't open a browser window automatically |

## Installing with pip

If you don't use uv:

```bash
pip install -e .
playwright install chromium
vip app
```
