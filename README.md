[![PyPI](https://img.shields.io/pypi/v/posit-vip)](https://pypi.org/project/posit-vip/)
[![CI](https://github.com/posit-dev/vip/actions/workflows/ci.yml/badge.svg)](https://github.com/posit-dev/vip/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/posit-vip)](https://pypi.org/project/posit-vip/)

# VIP - Verified Installation of Posit

An open-source, extensible test suite that validates Posit Team deployments are
installed correctly and functioning properly.

VIP uses **BDD-style tests** (pytest-bdd + Playwright) to verify Connect,
Workbench, and Package Manager.  Results are compiled into an **HTML report**
that can be published to a Connect server.

**Documentation:** https://posit-dev.github.io/vip/

## Quick start

```bash
uv pip install posit-vip
uv run playwright install chromium
vip verify --connect-url https://connect.example.com --interactive-auth
```

Run a specific test by name:

```bash
vip verify --connect-url https://connect.example.com -k test_login
```

With a configuration file:

```bash
cp vip.toml.example vip.toml     # edit with your deployment details
vip verify --config vip.toml
```

## CLI commands

| Command | Description |
|---|---|
| `vip verify` | Run verification tests against a Posit Team deployment |
| `vip status` | Quick health check for each configured product |
| `vip cleanup` | Delete VIP test credentials and resources |
| `vip report` | Render the HTML report from test results (requires [Quarto CLI](https://quarto.org/docs/download/)) |
| `vip app` | Launch the Shiny GUI for interactive test running |
| `vip auth` | Authentication tools (e.g. mint Connect API keys) |
| `vip cluster` | Cluster connection tools for Kubernetes deployments |

Run `vip --help` or `vip <command> --help` for full usage details.

## Shiny app (graphical test runner)

VIP includes a Shiny for Python app that lets you select test categories,
run tests, and view the report — all from a browser.  This is especially
convenient inside a Posit Workbench session (RStudio or Positron) where
the app opens in the Viewer pane.

```bash
uv run vip app
```

See the [Shiny App guide](https://posit-dev.github.io/vip/shiny-app/) for details.

## Development

See [docs/development.md](docs/development.md) for dev setup, linting, and formatting.

For the test architecture and four-layer design, see [docs/test-architecture.md](docs/test-architecture.md).

## License

MIT — see [LICENSE](LICENSE).
