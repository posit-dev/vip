# Fix: fail fast when a Workbench session cannot launch

*2026-05-29T21:11:57Z by Showboat 0.6.1*
<!-- showboat-id: 4858ab79-e705-473a-950b-40222af6c387 -->

## Problem

Running `vip verify --headless-auth --idp okta --workbench-url ...` against Workbench 2026.06 produced 10 failures, all reported as the opaque `AssertionError: Locator expected to be visible` after a 90s wait per test.

Investigation (the Playwright accessibility snapshot in each traceback) showed every launched session had status **Failed** with an *'Abnormal exits'* banner — the deployment genuinely could not launch sessions. The test was correctly detecting a real problem, but:

1. It waited the full `TIMEOUT_SESSION_START` (90s) for an `Active` status that would never come, then emitted an unhelpful 'Locator expected to be visible'.
2. The status locator only matched the pre-2026.06 `div[aria-label='Active']` markup; 2026.06 renders status as a `button` whose name is the status word.

## Fix

- `Homepage.session_row_status` now matches the status whether it is a legacy `div[aria-label]` or a 2026.06 `button` (text- or aria-label-named).
- New `wait_for_session_active()` helper polls for `Active` and **fails fast** with an actionable message the moment a terminal state (`Failed`) appears, instead of waiting out the timeout.
- All six session-active wait sites (ide_extensions, ide_launch, packages, data_sources, sessions, session_capacity) now use the helper.

```bash
uv run pytest selftests/test_workbench_session_active.py -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
7 passed
```

```bash
uv run python -c "
from vip_tests.workbench.conftest import TERMINAL_SESSION_FAILURE_STATES, _session_failure_message
from vip_tests.workbench.pages import Homepage
print(\"terminal states:\", TERMINAL_SESSION_FAILURE_STATES)
print()
print(\"status selector (matches legacy div AND 2026.06 button):\")
print(\" \", Homepage.session_row_status(\"main-1\", \"Active\"))
print()
print(\"fail-fast message instead of \x27Locator expected to be visible\x27:\")
print(\" \", _session_failure_message(\"VIP test - main-1\", \"Failed\"))
"
```

```output
terminal states: ('Failed',)

status selector (matches legacy div AND 2026.06 button):
  tr[aria-label$='main-1'] div[aria-label='Active'], tr[aria-label$='main-1'] button[aria-label='Active'], tr[aria-label$='main-1'] button:text-is('Active')

fail-fast message instead of 'Locator expected to be visible':
  Session 'VIP test - main-1' reached terminal state 'Failed' instead of Active — Workbench could not launch the session (abnormal exit). Verify the deployment can launch sessions: check the launcher, the session image, and available CPU/memory/quota.
```

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
132 files already formatted
```
