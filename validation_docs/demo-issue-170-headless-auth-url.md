# Fix: headless auth uses configured URL (#170)

*2026-04-18T02:12:31Z by Showboat 0.6.1*
<!-- showboat-id: 510ad4ff-fff9-4580-9eb9-d362b7f8af7b -->

Fixed issue #170: `vip verify --headless-auth` was navigating to `https://connect.example.com/__login__` instead of the URL from the user's vip.toml. The CLI was not forwarding `--vip-config` to pytest when relying on the default `vip.toml` in the CWD. Fix: always resolve the config path to an absolute path and pass it to pytest. Two new selftests in `selftests/test_cli_verify.py::TestVerifyLocalConfigPath` lock in the contract.

```bash
uv run pytest selftests/test_cli_verify.py::TestVerifyLocalConfigPath -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
2 passed
```

```bash
uv run pytest selftests/ -q > /tmp/pytest.log 2>&1 && grep -E "passed|failed|error" /tmp/pytest.log | grep -oE "(passed|failed|error)" | sort -u
```

```output
passed
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ | sed 's/^[0-9]* /N /' && echo 'All checks passed'
```

```output
All checks passed!
N files already formatted
All checks passed
```
