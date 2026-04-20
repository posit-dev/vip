# Fix: Create Connect API key via session cookies (issue #172)

*2026-04-20T22:22:53Z by Showboat 0.6.1*
<!-- showboat-id: c9bfac9e-db68-44dc-86fc-8f7bcfa7b286 -->

## Problem

`vip verify --headless-auth` worked on the first run but timed out on subsequent runs, waiting 5s for the "Manage Your API Keys" menu item. The bug was in `_create_api_key_via_ui` (src/vip/auth.py lines 613-713), which drove the Connect dashboard through Playwright — clicking the user dropdown, navigating to the API keys page, filling forms, scraping the generated key out of a dialog. The DOM assumptions didn't hold on repeated visits, so the warning "VIP: --headless-auth could not mint an API key" broke API-based tests.

## Fix

Replaced the Playwright UI flow with a direct call to the Connect REST API. The new `_create_api_key_via_session` lifts session cookies from the authenticated Playwright context and POSTs to `/__api__/v1/users/{guid}/keys` — the same endpoint the dashboard's "+ New API Key" button uses. Cookies are scoped to the Connect host (so IdP cookies don't leak), the XSRF double-submit token is echoed in the `X-Rsc-Xsrf` header, and orphan cleanup skips keys younger than an hour so concurrent `vip verify` runs don't step on each other.

## Proof

### New selftests for _create_api_key_via_session

Seven tests covering the happy path, XSRF, orphan cleanup order, recent-orphan skipping, cookie scoping, and two failure modes.

```bash
uv run pytest selftests/test_auth.py::TestCreateApiKeyViaSession -v 2>&1 | grep -E 'PASSED|FAILED|ERROR|test session starts|collected' | sed 's/ in [0-9.]*s//'
```

```output
============================= test session starts ==============================
collecting ... collected 7 items
selftests/test_auth.py::TestCreateApiKeyViaSession::test_happy_path_creates_key_and_sends_xsrf PASSED [ 14%]
selftests/test_auth.py::TestCreateApiKeyViaSession::test_deletes_orphan_vip_keys_before_creating PASSED [ 28%]
selftests/test_auth.py::TestCreateApiKeyViaSession::test_skips_recent_orphan_keys PASSED [ 42%]
selftests/test_auth.py::TestCreateApiKeyViaSession::test_cookies_filtered_to_connect_host PASSED [ 57%]
selftests/test_auth.py::TestCreateApiKeyViaSession::test_create_failure_returns_none PASSED [ 71%]
selftests/test_auth.py::TestCreateApiKeyViaSession::test_missing_xsrf_cookie_still_runs PASSED [ 85%]
selftests/test_auth.py::TestCreateApiKeyViaSession::test_missing_user_guid_returns_none PASSED [100%]
```

### Full selftests suite still passes

```bash
uv run pytest selftests/ -q 2>&1 | tail -1 | sed 's/ in [0-9.]*s//'
```

```output
267 passed, 6 warnings
```

### Lint and format clean

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

### Dead UI code is gone

The old UI-scraping functions are no longer in the tree.

```bash
if grep -qE '_create_api_key_via_ui|_delete_orphaned_keys' src/vip/auth.py; then echo 'FOUND (unexpected)'; else echo 'Removed.'; fi
```

```output
Removed.
```

### The new call sites

Both interactive and headless flows now use the session-cookie path.

```bash
grep -n '_create_api_key_via_session(page' src/vip/auth.py
```

```output
255:            api_key = _create_api_key_via_session(page, connect_url, key_name)
408:            api_key = _create_api_key_via_session(page, connect_url, key_name)
689:def _create_api_key_via_session(page: Page, connect_url: str, key_name: str) -> str | None:
```
