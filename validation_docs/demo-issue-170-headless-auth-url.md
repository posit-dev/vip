# Fix: headless auth uses configured URL (#170)

*2026-04-18T01:41:54Z by Showboat 0.6.1*
<!-- showboat-id: 7de8b5f8-07fb-430e-bed9-c35b0bf360f1 -->

Fixed issue #170: `vip verify --headless-auth` was navigating to the placeholder URL `https://connect.example.com/__login__` instead of the URL from the user's `vip.toml`. Root cause: when the user relied on the default `vip.toml` in the current directory (no `--config` flag), the CLI did not forward `--vip-config` to pytest. pytest's plugin then re-resolved `Path("vip.toml")` from whatever CWD pytest ended up in, which could differ from the user's CWD. Fix: resolve the config path to an absolute path in the CLI and always pass `--vip-config=<absolute-path>` to the pytest subprocess. Two new selftests in `selftests/test_cli_verify.py::TestVerifyLocalConfigPath` lock in the contract: `--vip-config` is always forwarded to pytest and is always an absolute path.

```bash
uv run pytest selftests/ -q 2>&1 | grep -E "passed|failed|error" | sed 's/ in [0-9.]*s//'
```

```output
245 passed, 4 warnings
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
99 files already formatted
All checks passed
```
