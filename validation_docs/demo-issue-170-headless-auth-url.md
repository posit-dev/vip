# Fix: headless auth uses configured URL (#170)

*2026-04-18T01:34:09Z by Showboat 0.6.1*
<!-- showboat-id: 8c2024ea-f33b-4d01-9c46-fe1e2bcde9ef -->

## Background

Issue #170: `vip verify --headless-auth` was navigating to the placeholder URL
`https://connect.example.com/__login__` instead of the URL from the user's
`vip.toml`.

Root cause: when the user relied on the default `vip.toml` in the current
directory (no `--config` flag), the CLI did not forward `--vip-config` to
pytest. pytest's plugin then re-resolved `Path("vip.toml")` from whatever CWD
pytest ended up in, which could differ from the user's CWD (pytest rootdir can
be set to the installed `vip_tests` package when it is passed as a test
target). When the config was not found there, pytest returned a default
`VIPConfig` with empty URLs — or, in other user setups, loaded the wrong file
entirely.

## The fix

Resolve the config path to an absolute path in the CLI and always pass
`--vip-config=<absolute-path>` to the pytest subprocess. This removes every
source of ambiguity between the CLI and pytest.

## Reproduction

Set up a project directory with a `vip.toml` that points to a real Connect URL.

```bash
mkdir -p /tmp/vip-170-demo && cat > /tmp/vip-170-demo/vip.toml <<'EOF'
[general]
deployment_name = "Issue 170 demo"

[connect]
url = "https://myserver.example.com/pct"

[auth]
provider = "password"
EOF
echo 'Created /tmp/vip-170-demo/vip.toml:'
cat /tmp/vip-170-demo/vip.toml
```

```output
Created /tmp/vip-170-demo/vip.toml:
[general]
deployment_name = "Issue 170 demo"

[connect]
url = "https://myserver.example.com/pct"

[auth]
provider = "password"
```

## Verify the command pytest receives

Simulate `vip verify --headless-auth` from the project directory and inspect
the pytest command that the CLI builds. The `--vip-config` flag must be
present and point to an absolute path — otherwise pytest will re-resolve
`Path("vip.toml")` from its own CWD and may load the wrong (or no) config.

```bash
cd /tmp/vip-170-demo && VIP_TEST_USERNAME=u VIP_TEST_PASSWORD=p /home/user/vip/.venv/bin/python <<'PY'
import os, argparse
from unittest.mock import patch, MagicMock
from vip.cli import _run_verify_local

captured = []
def fake_run(cmd, **kw):
    captured.append(cmd)
    r = MagicMock(); r.returncode=0
    return r

args = argparse.Namespace(
    config=None, connect_url=None, workbench_url=None, package_manager_url=None,
    report=None, interactive_auth=False, headless_auth=True, no_auth=False,
    extensions=[], categories=None, filter_expr=None, pytest_args=[],
    verbose=False, test_timeout=3600, idp=None,
)
with patch('vip.cli.subprocess.run', side_effect=fake_run), patch('vip.cli.sys.exit'):
    _run_verify_local(args)

cfg_args = [c for c in captured[0] if c.startswith('--vip-config=')]
assert cfg_args, 'pytest command is missing --vip-config'
cfg_path = cfg_args[0].split('=', 1)[1]
print('pytest received:', cfg_args[0])
print('absolute?       ', os.path.isabs(cfg_path))
print('file exists?    ', os.path.isfile(cfg_path))
PY
```

```output
Note: Workbench no URL given — Workbench tests will not be collected.
Note: Package Manager no URL given — Package Manager tests will not be collected.
pytest received: --vip-config=/tmp/vip-170-demo/vip.toml
absolute?        True
file exists?     True
```

## Plugin resolves the right URL even after CWD changes

Demonstrate that once the CLI passes an absolute path, the plugin's
`load_config` call is immune to pytest or user-shell CWD changes. If we
change CWD to `/` before loading the config (as could happen if pytest
rooted itself elsewhere), the user's real URL is still returned — not the
`connect.example.com` placeholder from the example template.

```bash
/home/user/vip/.venv/bin/python <<'PY'
import os
os.chdir('/')  # simulate pytest being in a different directory
from vip.config import load_config
cfg = load_config('/tmp/vip-170-demo/vip.toml')
print('Connect URL:  ', cfg.connect.url)
assert cfg.connect.url == 'https://myserver.example.com/pct'
assert 'connect.example.com' not in cfg.connect.url
print('OK: real URL is loaded, not the placeholder')
PY
```

```output
Connect URL:   https://myserver.example.com/pct
OK: real URL is loaded, not the placeholder
```

## Selftests pass (including new regression tests)

```bash
uv run pytest selftests/test_cli_verify.py::TestVerifyLocalConfigPath -v 2>&1 | grep -E 'PASSED|FAILED|ERROR' | sed 's/ in [0-9.]*s//'
```

```output
selftests/test_cli_verify.py::TestVerifyLocalConfigPath::test_default_vip_toml_passed_as_absolute_path PASSED [ 50%]
selftests/test_cli_verify.py::TestVerifyLocalConfigPath::test_explicit_config_passed_as_absolute_path PASSED [100%]
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
245 passed, 4 warnings
```

## Lint and format

Ruff check and format pass on all Python directories.

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
99 files already formatted
```
