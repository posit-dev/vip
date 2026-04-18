# Fix: headless auth uses configured URL (#170)

*2026-04-18T02:00:19Z by Showboat 0.6.1*
<!-- showboat-id: 85aad8eb-f2a8-4de5-96b8-78e6ef294e48 -->

Fixed issue #170: `vip verify --headless-auth` was navigating to `https://connect.example.com/__login__` instead of the URL from the user's vip.toml. The CLI was not forwarding `--vip-config` to pytest when relying on the default `vip.toml` in the CWD. Fix: always resolve the config path to an absolute path and pass it to pytest. Two new selftests in `selftests/test_cli_verify.py::TestVerifyLocalConfigPath` lock in the contract.

```bash
uv run pytest selftests/ -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
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
