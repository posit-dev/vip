# fix(connect): skip user-list assertion when no test user is configured

*2026-06-11T15:58:57Z by Showboat 0.6.1*
<!-- showboat-id: 89da263a-c5e9-4965-b092-0c1bce3d7175 -->

When VIP_TEST_USERNAME is unset or empty (common with --interactive-auth), the 'the test user exists in the user list' step previously failed with a confusing assertion error. The fix adds a pytest.skip() guard before the assertion so the test skips gracefully instead of failing.

The changed lines in src/vip_tests/connect/test_users.py:

```bash
grep -n 'pytest.skip\|import pytest\|test_username' src/vip_tests/connect/test_users.py
```

```output
5:import pytest
52:def check_test_user_in_list(user_list, test_username):
53:    if not test_username or not test_username.strip():
54:        pytest.skip("No test user configured — skipping user lookup assertion")
55:    expected = test_username.split("@", 1)[0]
58:        f"Test user {expected!r} (from {test_username!r}) not found in user list: {usernames}"
```

Ruff lint and format checks pass:

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && echo 'ruff check: all passed'
```

```output
All checks passed!
ruff check: all passed
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ && echo 'ruff format: all formatted'
```

```output
143 files already formatted
ruff format: all formatted
```

Selftests pass:

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
685 passed, 3 skipped, 20 warnings
```

Product test collection (dry-run) succeeds, showing the patched test is collectable:

```bash
uv run pytest src/vip_tests/ --collect-only -q 2>&1 | grep -E 'collected|error' | sed 's/ in [0-9.]*s//' | head -5
```

```output
6/113 tests collected (107 deselected)
```
