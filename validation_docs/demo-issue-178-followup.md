# Follow-up: Address Copilot review comments for #191

*2026-04-18T01:24:36Z by Showboat 0.6.1*
<!-- showboat-id: de2120da-de9b-409a-8fd3-5ff58d08ff00 -->

#191 merged with three Copilot review comments still open. This follow-up addresses all three:

1. **cli.py --help wording** — use TOML section syntax (`set deploy_timeout under [connect]`) rather than a dotted path (`connect.deploy_timeout`), since users edit vip.toml by section, not by dotted key.
2. **Shared `DEFAULT_TEST_TIMEOUT_SECONDS` constant** — argparse default and selftest helper now reference the same module-level constant, so they stay in lockstep.
3. **Real argparse-default test** — added `test_argparse_default_matches_constant` which invokes the real `vip verify` parser via `main()` and asserts the parsed default equals the constant. This guards against drift even if the helper's own default is changed in isolation.

### Updated --help text uses TOML section syntax

```bash
uv run vip verify --help 2>&1 | grep -A5 -- '--test-timeout'
```

```output
                  [--test-timeout TEST_TIMEOUT] [--k8s] [--site SITE]
                  [--namespace NAMESPACE] [--name NAME] [--image IMAGE]
                  [--timeout TIMEOUT] [--config-only]
                  [pytest_args ...]

Run VIP tests against a Posit Team deployment.
--
  --test-timeout TEST_TIMEOUT
                        Timeout in seconds for the pytest subprocess (default:
                        3600). A full Connect run includes content deployments
                        that each take several minutes (R package restore,
                        Python venv creation), so raise this further for large
                        suites or slow servers. For per-deploy limits, set
```

### Shared constant is reachable and holds the expected value

```bash
uv run python -c 'from vip.cli import DEFAULT_TEST_TIMEOUT_SECONDS; print(DEFAULT_TEST_TIMEOUT_SECONDS)'
```

```output
3600
```

### The timeout-group selftests all pass, including the new argparse test

```bash
uv run pytest selftests/test_cli_verify.py::TestVerifyLocalTestTimeout -v 2>&1 | grep -E 'PASSED|FAILED|ERROR' | sed 's/ in [0-9.]*s//'
```

```output
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_argparse_default_matches_constant PASSED [ 25%]
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_default_timeout_passed_to_subprocess PASSED [ 50%]
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_custom_timeout_passed_through PASSED [ 75%]
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_timeout_expired_exits_with_error PASSED [100%]
```

### Full selftest suite and lint/format still pass

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
244 passed, 4 warnings
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
99 files already formatted
```
