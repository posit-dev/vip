# Fix: default --test-timeout too short for Connect deploys

*2026-04-18T01:14:21Z by Showboat 0.6.1*
<!-- showboat-id: 02f8bc3b-613e-490c-b880-ccdfe7295dc9 -->

Issue #178 reported that the default --test-timeout of 180 seconds is too short for Connect content-deployment tests (e.g. test_deploy_shiny), which need to install packages server-side and routinely take 3-5 minutes each.

This change raises the default from 180 seconds (3 min) to 3600 seconds (60 min) and updates the --help text to point users at connect.deploy_timeout in vip.toml for per-deploy limits.

### New default surfaced via --help

```bash
uv run vip verify --help 2>&1 | grep -A4 -- '--test-timeout'
```

```output
                  [--test-timeout TEST_TIMEOUT] [--k8s] [--site SITE]
                  [--namespace NAMESPACE] [--name NAME] [--image IMAGE]
                  [--timeout TIMEOUT] [--config-only]
                  [pytest_args ...]

--
  --test-timeout TEST_TIMEOUT
                        Timeout in seconds for the pytest subprocess (default:
                        3600). A full Connect run includes content deployments
                        that each take several minutes (R package restore,
                        Python venv creation), so raise this further for large
```

### Selftests pass, including the updated default-timeout assertion

```bash
uv run pytest selftests/test_cli_verify.py::TestVerifyLocalTestTimeout -v 2>&1 | grep -E 'PASSED|FAILED|ERROR' | sed 's/ in [0-9.]*s//'
```

```output
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_default_timeout_is_3600 PASSED [ 33%]
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_custom_timeout_passed_through PASSED [ 66%]
selftests/test_cli_verify.py::TestVerifyLocalTestTimeout::test_timeout_expired_exits_with_error PASSED [100%]
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
243 passed, 4 warnings
```

### Lint and format pass

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
99 files already formatted
```
