# Fix: headless auth uses configured URL (#170)

*2026-04-18T01:41:54Z by Showboat 0.6.1*
<!-- showboat-id: 7de8b5f8-07fb-430e-bed9-c35b0bf360f1 -->

## Background

Issue #170: `vip verify --headless-auth` was navigating to the placeholder URL
`https://connect.example.com/__login__` instead of the URL from the user's
`vip.toml`.

Root cause: when the user relied on the default `vip.toml` in the current
directory (no `--config` flag), the CLI did not forward `--vip-config` to
pytest. pytest's plugin then re-resolved `Path("vip.toml")` from whatever CWD
pytest ended up in, which could differ from the user's CWD (pytest rootdir
can be set to the installed `vip_tests` package when it is passed as a test
target). When the config was not found there, pytest returned a default
`VIPConfig` with empty URLs.

## The fix

Resolve the config path to an absolute path in the CLI and always pass
`--vip-config=<absolute-path>` to the pytest subprocess. This removes every
source of ambiguity between the CLI and pytest.

## Reproduction

Write a minimal `vip.toml` that points at a customer-specific URL.

```bash
mkdir -p /tmp/vip-170-demo && cat > /tmp/vip-170-demo/vip.toml <<"EOF"
[connect]
enabled = true
url = "https://connect.customer.internal"

[auth]
provider = "oidc"
idp = "keycloak"
username = "admin"
password = "dummy"
EOF
grep url /tmp/vip-170-demo/vip.toml
```

```output
url = "https://connect.customer.internal"
```

## With the fix: pytest gets an absolute `--vip-config`

Simulate what the CLI now does in the default-vip.toml case: resolve the
default `vip.toml` to an absolute path and forward it to pytest. Before the
fix, the CLI passed nothing and pytest re-resolved `Path("vip.toml")`
relative to its own rootdir, which could drift to the installed `vip_tests`
package.

```bash
cd /tmp/vip-170-demo && uv --project /home/user/vip run python -c "
from pathlib import Path
default = Path(\"vip.toml\")
resolved = str(default.resolve())
print(f\"--vip-config={resolved}\")
assert Path(resolved).is_absolute(), \"not absolute\"
assert Path(resolved).is_file(), \"not a file\"
"
```

```output
--vip-config=/tmp/vip-170-demo/vip.toml
```

## The plugin now loads the user's URL

Using that absolute path, the pytest plugin loads the real URL. Previously,
without `--vip-config`, the plugin would fall back to an empty default
config, and headless auth would navigate to `connect.example.com` (the value
hard-coded in `vip.toml.example`, which some users had copied but never
customised).

```bash
uv --project /home/user/vip run python -c "
from vip.config import load_config
cfg = load_config(\"/tmp/vip-170-demo/vip.toml\")
print(f\"connect.url = {cfg.connect.url}\")
assert cfg.connect.url == \"https://connect.customer.internal\"
assert \"example.com\" not in cfg.connect.url
"
```

```output
connect.url = https://connect.customer.internal
```

## Regression tests

Two new selftests in `selftests/test_cli_verify.py` lock in the contract:
`--vip-config` is always forwarded to pytest and is always an absolute path.

```bash
uv run pytest selftests/test_cli_verify.py::TestVerifyLocalConfigPath -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
2 passed
```

## Full selftest suite

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
245 passed, 4 warnings
```

## Lint

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
99 files already formatted
```
