# fix(workbench): stop asserting exact username on homepage login check

*2026-06-11T16:00:04Z by Showboat 0.6.1*
<!-- showboat-id: ab2f99a5-d37e-448e-bdfc-5147cba2a1e8 -->

The Workbench new homepage shows the user's display name (e.g. 'Shane Halloran') in the #current-user element rather than the login username (e.g. 'shaneh02'). The old assertion used to_have_text(test_username) which failed whenever the display name differed from the login ID.

The fix (issue #273 option 3): assert the #current-user element is visible and non-empty. Reaching the homepage already proves login succeeded -- we do not need to verify which specific text appears.

Note from issue commenter: this test can fail on legacy homepages (users who have not switched to the new homepage). The fix does not attempt to support the legacy homepage; if a test user is on the legacy homepage the visible/non-empty assertion should still pass as long as the element exists, but the surrounding page structure may differ.

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1
```

```output
143 files already formatted
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
685 passed, 3 skipped, 20 warnings
```

```bash
uv run pytest src/vip_tests/ --collect-only -q 2>&1 | grep -E 'collected|selected' | sed 's/ in [0-9.]*s//'
```

```output
6/113 tests collected (107 deselected)
```

```bash
grep -n 'not_to_be_empty\|to_be_visible\|current_user_displayed' src/vip_tests/workbench/test_auth.py
```

```output
70:def current_user_displayed(page: Page):
72:    expect(current_user).to_be_visible(timeout=TIMEOUT_DIALOG)
73:    expect(current_user).not_to_be_empty()
```

```bash
grep -n 'current user' src/vip_tests/workbench/test_auth.feature
```

```output
11:    And the current user element is visible and non-empty in the header
```
