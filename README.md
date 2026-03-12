# VIP - Verified Installation of Posit

An open-source, extensible test suite that validates Posit Team deployments are
installed correctly and functioning properly.

VIP uses **BDD-style tests** (pytest-bdd + Playwright) to verify Connect,
Workbench, and Package Manager.  Results are compiled into a **Quarto report**
that can be published to a Connect server.

## Quick start

```bash
git clone https://github.com/posit-dev/vip.git
cd vip
uv sync && uv run playwright install chromium

cp vip.toml.example vip.toml     # edit with your deployment details
uv run pytest                     # run all tests
uv run pytest -m connect          # run tests for a single product
```

## Documentation

| Guide | Description |
|---|---|
| [Getting Started](docs/getting-started.md) | Prerequisites, installation, and first run |
| [Configuration](docs/configuration.md) | `vip.toml` settings and environment variables |
| [Authentication](docs/authentication.md) | Password, LDAP, OIDC, and interactive auth flows |
| [Deployment Verification](docs/deployment-verification.md) | `vip verify`, cluster setup, and K8s integration |
| [Test Categories](docs/test-categories.md) | Test markers, version gating, and extensibility |
| [Reporting](docs/reporting.md) | Generating and publishing the Quarto report |
| [Development](docs/development.md) | Dev setup, linting, formatting, and design principles |

## License

MIT — see [LICENSE](LICENSE).
