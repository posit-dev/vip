# Fix: headless auth missing chromium dependencies (#169)

*2026-04-20T20:37:31Z by Showboat 0.6.1*
<!-- showboat-id: aa58b066-1edd-4d90-b7d9-9450429a8883 -->

When chromium launches without its system libraries (seen on fresh Ubuntu 24 installs), vip verify --headless-auth used to fail with a raw shared-library error. This change detects that failure in auth.py and rewrites it into an AuthConfigError pointing the user at the fix, and updates the quickstart instructions to use playwright install --with-deps chromium so fresh installs get the system packages up front.

## 1. New selftests for the remediation hint

```bash
uv run pytest selftests/test_auth.py -v 2>&1 | sed 's/ in [0-9.]*s//' | tail -12
```

```output
configfile: pyproject.toml
plugins: anyio-4.12.1, posit-vip-0.24.7, playwright-0.7.2, shiny-1.5.1, cov-7.1.0, locust-2.43.4, xdist-3.8.0, base-url-2.1.0, bdd-8.1.0
collecting ... collected 6 items

selftests/test_auth.py::TestStartHeadlessAuthValidation::test_no_urls_raises_even_with_warm_cache PASSED [ 16%]
selftests/test_auth.py::TestStartHeadlessAuthValidation::test_no_urls_raises_without_cache PASSED [ 33%]
selftests/test_auth.py::TestStartHeadlessAuthPlaywrightErrors::test_timeout_during_login_becomes_auth_config_error PASSED [ 50%]
selftests/test_auth.py::TestStartHeadlessAuthPlaywrightErrors::test_playwright_error_during_login_becomes_auth_config_error PASSED [ 66%]
selftests/test_auth.py::TestStartHeadlessAuthPlaywrightErrors::test_missing_chromium_system_deps_gives_remediation PASSED [ 83%]
selftests/test_auth.py::TestStartHeadlessAuthPlaywrightErrors::test_unrelated_playwright_launch_error_propagates PASSED [100%]

============================== 6 passed ===============================
```

## 2. Remediation message exercised end-to-end (via the auth module)

```bash
uv run python -c "
from unittest.mock import MagicMock, patch
from playwright.sync_api import Error as PlaywrightError
from vip.auth import AuthConfigError, start_headless_auth

pw = MagicMock()
pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
    'Host system is missing dependencies to run browsers.'
)
with patch('vip.auth.sync_playwright', return_value=pw):
    try:
        start_headless_auth(connect_url='https://c.example.com', username='u', password='p')
    except AuthConfigError as exc:
        print(exc)
"
```

```output
Chromium could not launch because required system libraries are missing on this host. Install them with:

    uv run playwright install --with-deps chromium

(On Linux this uses sudo + apt-get to install the missing packages.)
```

## 3. Full selftest suite — no regressions

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
260 passed, 6 warnings
```

## 4. Lint + format

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
101 files already formatted
```
