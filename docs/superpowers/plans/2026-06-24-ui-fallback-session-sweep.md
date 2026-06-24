# UI-based fallback session sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quit orphaned VIP-named Workbench sessions via the homepage UI when the session API is unreachable, so cleanup works on deployments (e.g. `workbench.posit.it`) where `/api/sessions` 404s.

**Architecture:** Add an API-reachability probe to `WorkbenchClient`. Add a UI-driven sweep helper and a cookie-auth reachability wrapper to the Workbench conftest. Hook the UI sweep into the existing per-test `_cleanup_sessions` teardown, gated on reachability cached once per session — so the UI path is taken only where the API is absent (zero added cost otherwise).

**Tech Stack:** Python, pytest, pytest-bdd, Playwright (sync API), httpx.

## Global Constraints

- Ruff `E,F,I,UP`, line length 100; CI pins ruff 0.15.0. Run `uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/` and `uvx ruff@0.15.0 format --check ...`.
- All commands run through `uv` (no bare `python`/`pip`).
- Clients use raw httpx; no product SDKs.
- Cleanup helpers must be best-effort and **never raise** (a cleanup failure must not fail the test that triggered it).
- Only ever act on VIP-named sessions (`is_vip_session`); never use "Quit All".
- Selftests cover pure pieces; live Playwright click-through is exercised against a real deployment.

---

### Task 1: `WorkbenchClient.sessions_api_reachable()`

**Files:**
- Modify: `src/vip/clients/workbench.py` (add method after `list_sessions`, ~line 81)
- Test: `selftests/test_workbench_cleanup.py` (reuse existing `_client_with_handler`)

**Interfaces:**
- Produces: `WorkbenchClient.sessions_api_reachable() -> bool` — `True` iff `GET /api/sessions` returns status `< 400`; `False` on `>= 400` or any transport exception. Never raises.

- [ ] **Step 1: Write the failing tests**

Append to `selftests/test_workbench_cleanup.py`:

```python
def test_sessions_api_reachable_true_on_200():
    wc = _client_with_handler(lambda r: httpx.Response(200, json=[]))
    assert wc.sessions_api_reachable() is True


def test_sessions_api_reachable_false_on_404():
    wc = _client_with_handler(lambda r: httpx.Response(404, text="<html>not found</html>"))
    assert wc.sessions_api_reachable() is False


def test_sessions_api_reachable_false_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert wc.sessions_api_reachable() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k sessions_api_reachable -v`
Expected: FAIL — `AttributeError: 'WorkbenchClient' object has no attribute 'sessions_api_reachable'`.

- [ ] **Step 3: Implement the method**

In `src/vip/clients/workbench.py`, immediately after the `list_sessions` method:

```python
    def sessions_api_reachable(self) -> bool:
        """Return True if the session-list API endpoint is served here.

        Some deployments do not expose ``/api/sessions`` (it 404s, served by
        the SPA fallback).  There, the API-based cleanup silently no-ops and
        callers should fall back to UI-driven cleanup.  Returns True iff the
        endpoint responds with a status ``< 400``.  Returns False on any HTTP
        error status or transport exception; never raises.
        """
        try:
            resp = self._client.get("/api/sessions")
        except Exception:
            return False
        return resp.status_code < 400
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k sessions_api_reachable -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/vip/clients/workbench.py selftests/test_workbench_cleanup.py
git commit -m "feat(workbench): add WorkbenchClient.sessions_api_reachable probe"
```

---

### Task 2: `_vip_names_from_select_labels()` pure helper

**Files:**
- Modify: `src/vip_tests/workbench/conftest.py` (import `is_vip_session`; add helper near the other session helpers, e.g. just before `_quit_vip_sessions_via_cookies`)
- Test: `selftests/test_workbench_cleanup.py`

**Interfaces:**
- Consumes: `is_vip_session` from `vip.clients.workbench`.
- Produces: `_vip_names_from_select_labels(labels: list[str]) -> list[str]` — given session-row checkbox `aria-label`s of the form `"select <session name>"`, returns the names (prefix stripped) that match `is_vip_session`, preserving input order.

- [ ] **Step 1: Write the failing test**

Append to `selftests/test_workbench_cleanup.py`:

```python
def test_vip_names_from_select_labels_keeps_only_vip():
    from vip_tests.workbench.conftest import _vip_names_from_select_labels

    labels = [
        "select VIP test_jobs.py - gw0-1",
        "select My real work",
        "select _vip_cap_1_default_0",
        "garbage without prefix",
        "VIP no select prefix",
    ]
    assert _vip_names_from_select_labels(labels) == [
        "VIP test_jobs.py - gw0-1",
        "_vip_cap_1_default_0",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k vip_names_from_select_labels -v`
Expected: FAIL — `ImportError: cannot import name '_vip_names_from_select_labels'`.

- [ ] **Step 3: Implement the helper**

In `src/vip_tests/workbench/conftest.py`, change the import on line 17 from:

```python
from vip.clients.workbench import WorkbenchClient
```

to:

```python
from vip.clients.workbench import WorkbenchClient, is_vip_session
```

Then add, just above `def _quit_vip_sessions_via_cookies(`:

```python
_SELECT_PREFIX = "select "


def _vip_names_from_select_labels(labels: list[str]) -> list[str]:
    """Extract VIP-named session names from session-row checkbox aria-labels.

    Each homepage session row exposes a checkbox whose aria-label is
    ``"select <session name>"``.  Returns the names (without the ``"select "``
    prefix) that match :func:`is_vip_session`, so a real user's sessions are
    never selected for quitting.  Input order is preserved.
    """
    names: list[str] = []
    for label in labels:
        if not label.startswith(_SELECT_PREFIX):
            continue
        name = label[len(_SELECT_PREFIX) :]
        if is_vip_session(name):
            names.append(name)
    return names
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k vip_names_from_select_labels -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/vip_tests/workbench/conftest.py selftests/test_workbench_cleanup.py
git commit -m "test(workbench): add VIP select-label name filter helper"
```

---

### Task 3: `_quit_vip_sessions_via_ui()` UI sweep helper

**Files:**
- Modify: `src/vip_tests/workbench/conftest.py` (add after `_quit_vip_sessions_via_cookies`)
- Test: `selftests/test_workbench_cleanup.py`

**Interfaces:**
- Consumes: `_vip_names_from_select_labels` (Task 2); `Homepage.session_checkbox`, `Homepage.QUIT_BUTTON`, `Homepage.CONFIRM_QUIT`, `Homepage.FORCE_QUIT`, `Homepage.CONFIRM_FORCE_QUIT`; `TIMEOUT_PAGE_LOAD`, `TIMEOUT_QUICK`.
- Produces: `_quit_vip_sessions_via_ui(page: Page, base_url: str, *, max_iterations: int = 10) -> int` — navigates the homepage and quits VIP-named sessions via the UI; returns the count of sessions a quit was issued for. Never raises.

- [ ] **Step 1: Write the failing test (never-raises contract)**

Append to `selftests/test_workbench_cleanup.py`:

```python
def test_quit_vip_sessions_via_ui_never_raises_on_failure():
    """A navigation/Playwright failure must not propagate out of cleanup."""
    from vip_tests.workbench.conftest import _quit_vip_sessions_via_ui

    class _BoomPage:
        def goto(self, *args, **kwargs):
            raise RuntimeError("navigation failed")

    assert _quit_vip_sessions_via_ui(_BoomPage(), "https://wb.example.com") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k quit_vip_sessions_via_ui -v`
Expected: FAIL — `ImportError: cannot import name '_quit_vip_sessions_via_ui'`.

- [ ] **Step 3: Implement the helper**

In `src/vip_tests/workbench/conftest.py`, immediately after `_quit_vip_sessions_via_cookies`:

```python
def _quit_vip_sessions_via_ui(page: Page, base_url: str, *, max_iterations: int = 10) -> int:
    """Quit orphaned VIP-named sessions through the homepage UI.

    Fallback for deployments whose session API is unreachable (see
    :meth:`WorkbenchClient.sessions_api_reachable`), where the cookie/API sweep
    is a no-op.  Navigates to the homepage, selects only VIP-named session rows
    (validated via :func:`is_vip_session`), clicks Quit, and dismisses any
    confirmation/force-quit dialogs, repeating until no VIP rows remain or
    *max_iterations* is hit.  Never uses "Quit All".  Best-effort: all
    Playwright errors are swallowed and it never raises.  Returns the number of
    sessions for which a quit was issued.
    """
    quit_count = 0
    try:
        page.goto(base_url.rstrip("/") + "/home", wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
        for _ in range(max_iterations):
            checkboxes = page.locator("[aria-label^='select ']")
            labels = [
                checkboxes.nth(i).get_attribute("aria-label") or ""
                for i in range(checkboxes.count())
            ]
            vip_names = _vip_names_from_select_labels(labels)
            if not vip_names:
                break
            selected = 0
            for name in vip_names:
                try:
                    page.locator(Homepage.session_checkbox(name)).first.click(timeout=TIMEOUT_QUICK)
                    selected += 1
                except Exception:
                    continue
            if selected == 0:
                break
            try:
                page.locator(Homepage.QUIT_BUTTON).first.click(timeout=TIMEOUT_QUICK)
            except Exception:
                break
            for sel in (Homepage.CONFIRM_QUIT, Homepage.FORCE_QUIT, Homepage.CONFIRM_FORCE_QUIT):
                try:
                    page.locator(sel).first.click(timeout=TIMEOUT_QUICK)
                except Exception:
                    pass
            quit_count += selected
            try:
                page.reload(wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
            except Exception:
                break
    except Exception:
        pass
    return quit_count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k quit_vip_sessions_via_ui -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/vip_tests/workbench/conftest.py selftests/test_workbench_cleanup.py
git commit -m "test(workbench): add UI-driven VIP session sweep helper"
```

---

### Task 4: Gate the fallback into `_cleanup_sessions`

**Files:**
- Modify: `src/vip_tests/workbench/conftest.py` (add `_session_api_reachable_via_cookies`; add `"api_reachable"` to `_wb_cleanup_state`; extend `_cleanup_sessions` teardown)
- Test: `selftests/test_workbench_cleanup.py`

**Interfaces:**
- Consumes: `WorkbenchClient.sessions_api_reachable` (Task 1); `_quit_vip_sessions_via_ui` (Task 3).
- Produces: `_session_api_reachable_via_cookies(base_url: str, cookies: dict[str, str], *, insecure: bool, ca_bundle) -> bool` — reachability for a cookie-authenticated scratch client; `False` on any error. Reachability is computed once per session (cached on `_wb_cleanup_state["api_reachable"]`); when `False`, `_cleanup_sessions` runs the UI sweep.

- [ ] **Step 1: Write the failing test**

Append to `selftests/test_workbench_cleanup.py`:

```python
def test_session_api_reachable_via_cookies_delegates_and_never_raises(monkeypatch):
    from vip_tests.workbench import conftest as wb

    monkeypatch.setattr(wb.WorkbenchClient, "sessions_api_reachable", lambda self: True)
    assert (
        wb._session_api_reachable_via_cookies(
            "https://wb.example.com", {"c": "v"}, insecure=False, ca_bundle=None
        )
        is True
    )

    def boom(self):
        raise RuntimeError("nope")

    monkeypatch.setattr(wb.WorkbenchClient, "sessions_api_reachable", boom)
    assert (
        wb._session_api_reachable_via_cookies(
            "https://wb.example.com", {}, insecure=False, ca_bundle=None
        )
        is False
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k session_api_reachable_via_cookies -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_session_api_reachable_via_cookies'`.

- [ ] **Step 3: Implement the wrapper**

In `src/vip_tests/workbench/conftest.py`, immediately after `_quit_vip_sessions_via_ui`:

```python
def _session_api_reachable_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
) -> bool:
    """Whether the session API is reachable for a cookie-authenticated client.

    Mirrors :func:`_quit_vip_sessions_via_cookies`: uses a scratch
    ``WorkbenchClient`` so the session-scoped client's cookie jar is untouched.
    Returns ``False`` on any error.
    """
    try:
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle)
        try:
            scratch.set_cookies(cookies)
            return scratch.sessions_api_reachable()
        finally:
            scratch.close()
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_workbench_cleanup.py -k session_api_reachable_via_cookies -v`
Expected: 1 passed.

- [ ] **Step 5: Add the `api_reachable` cache slot**

In `_wb_cleanup_state` (session-scoped fixture), change:

```python
    state: dict[str, object] = {"cookies": None, "base_url": None}
```

to:

```python
    state: dict[str, object] = {"cookies": None, "base_url": None, "api_reachable": None}
```

- [ ] **Step 6: Wire the gated UI fallback into `_cleanup_sessions`**

In `_cleanup_sessions`, replace the trailing `_quit_vip_sessions_via_cookies(...)` call with the call **plus** the gated fallback:

```python
    _quit_vip_sessions_via_cookies(
        workbench_client.base_url,
        cookies,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
    )
    # If the session API is unreachable on this deployment (e.g. /api/sessions
    # 404s), the cookie/API sweep above is a no-op. Detect reachability once per
    # session (cached on _wb_cleanup_state) and, when unavailable, fall back to a
    # UI-driven sweep that quits orphaned VIP sessions via the homepage.
    if _wb_cleanup_state["api_reachable"] is None:
        _wb_cleanup_state["api_reachable"] = _session_api_reachable_via_cookies(
            workbench_client.base_url,
            cookies,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
        )
    if not _wb_cleanup_state["api_reachable"]:
        _quit_vip_sessions_via_ui(page, workbench_client.base_url)
```

- [ ] **Step 7: Verify the whole suite is green and lint-clean**

Run:
```bash
uv run pytest selftests/ -q
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format --check src/ src/vip_tests/ selftests/ examples/
```
Expected: selftests all pass (no failures/errors); ruff "All checks passed!" and "already formatted".

- [ ] **Step 8: Commit**

```bash
git add src/vip_tests/workbench/conftest.py selftests/test_workbench_cleanup.py
git commit -m "fix(workbench): fall back to UI session sweep when API is unreachable"
```

---

## Live verification (manual, real deployment — not CI)

The UI click-through only runs against a real Workbench. After implementation,
optionally confirm against a deployment whose API path is absent (e.g.
`workbench.posit.it`): run the Workbench suite with `--interactive-auth` and
confirm orphaned `VIP …` sessions are quit by the per-test fallback. This step
is informational; CI cannot perform it.

## Notes for the implementer

- Do not change `quit_vip_sessions`' signature/behavior — other callers
  (`_wb_cleanup_state`, `test_session_capacity_k8s`) depend on it.
- After all tasks, per project convention the design spec and this plan are
  removed (`docs/superpowers/specs/2026-06-24-ui-fallback-session-sweep-design.md`
  and this file) as the final step of implementation.
