[![PyPI](https://img.shields.io/pypi/v/posit-vip)](https://pypi.org/project/posit-vip/)
[![CI](https://github.com/posit-dev/vip/actions/workflows/ci.yml/badge.svg)](https://github.com/posit-dev/vip/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/posit-vip)](https://pypi.org/project/posit-vip/)

# VIP - Verified Installation of Posit

An open-source, extensible test suite that validates Posit Team deployments are
installed correctly and functioning properly.

VIP uses BDD-style tests (pytest-bdd + Playwright) to verify Connect,
Workbench, and Package Manager deployments. Results can be viewed
from the command-line output or compiled into an HTML report.

**Documentation:** https://posit-dev.github.io/vip/

## Quick start

```bash
uv tool install posit-vip
vip install
vip verify --connect-url https://connect.example.com --interactive-auth
```

On a headless server (no display), use `--headless-auth` instead:

```bash
vip verify --config vip.toml --headless-auth
```

Run a specific test by name:

```bash
vip verify --connect-url https://connect.example.com --filter test_login
```

With a configuration file:

```bash
cp vip.toml.example vip.toml     # edit with your deployment details
vip verify --config vip.toml
```

## Uninstalling

To reverse what `vip install` (or `just setup`) did:

```bash
vip uninstall        # dry run; prints the full plan including any sudo command
vip uninstall --yes  # remove Playwright cache + manifest; prints the sudo command
                     # for any system packages so you can remove them yourself

uv tool uninstall posit-vip  # remove vip itself once you're done
```

`vip uninstall` only removes packages and files that `vip install` recorded
in `.vip-install.json`; anything that was already on your machine before
running `vip install` is left alone.

If a Connect URL is configured (in `vip.toml` or via `--connect-url`),
`vip uninstall` chains `vip cleanup` first to remove `_vip_test`-tagged
content from Connect.

## CLI commands

| Command | Description |
|---|---|
| `vip verify` | Run verification tests against a Posit Team deployment |
| `vip status` | Quick health check for each configured product |
| `vip cleanup` | Delete VIP `_vip_test` content from Connect |
| `vip report` | Render the HTML report from test results (requires [Quarto CLI](https://quarto.org/docs/download/)) |
| `vip auth` | Authentication tools (e.g. mint Connect API keys) |
| `vip version` | Print the vip version and the minimum supported Posit Team version |
| `vip --version` | Print the installed vip version |

Run `vip --help` or `vip <command> --help` for full usage details.

## CI / pipeline integration

VIP emits machine-readable output for security-ops and CI/CD pipelines.

`vip verify` always writes `report/results.json` (and `report/failures.json` on
failures). Add JUnit XML and/or SARIF with `--format`:

```bash
vip verify --format json,junit,sarif
# report/results.json   (always)
# report/junit.xml       (--format junit)  -> CI test dashboards
# report/results.sarif   (--format sarif)  -> GitHub code scanning / secops
```

The `--ci` preset bundles all three formats with concise tracebacks (`--tb=short`)
and overrides `--format` if both are given. Run it without `--interactive-auth`/
`--headless-auth` -- combining them is an error, since `--ci` is meant for
non-interactive pipelines:

```bash
vip verify --ci
```

### Container

An official image is published to `ghcr.io/posit-dev/vip`. The entrypoint is the
`vip` CLI; the default subcommand is `verify`. Because `docker run` args replace
the default command (they do not append to it), name the `verify` subcommand
explicitly when passing verify flags:

```bash
# bare invocation runs `vip verify`:
docker run --rm -v "$PWD/vip.toml:/app/vip.toml" ghcr.io/posit-dev/vip
# CI preset (name the subcommand so args don't replace it):
docker run --rm -v "$PWD/vip.toml:/app/vip.toml" ghcr.io/posit-dev/vip verify --ci
# other subcommands are reachable too:
docker run --rm -v "$PWD/vip.toml:/app/vip.toml" ghcr.io/posit-dev/vip status --json
```

## Development

See [docs/development.md](docs/development.md) for dev setup, linting, and formatting.

For the test architecture and four-layer design, see [docs/test-architecture.md](docs/test-architecture.md).

## License

MIT — see [LICENSE](LICENSE).
