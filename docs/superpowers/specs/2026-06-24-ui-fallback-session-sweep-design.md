# UI-based fallback session sweep — design

Date: 2026-06-24
Status: approved (pending spec review)

## Problem

VIP Workbench tests clean up the sessions they create via the UI
(`test_sessions.py::session_cleaned_up`). As a safety net, the per-test
`_cleanup_sessions` fixture and the end-of-run `_wb_cleanup_state` fixture also
sweep *all* VIP-named sessions through the API (`WorkbenchClient.quit_vip_sessions`
→ `GET`/`DELETE /api/sessions`).

On some deployments (observed on `workbench.posit.it`) the session API path
returns **404** — `/api/sessions` is not served there. `list_sessions()` treats
any non-200 as "no sessions", so `quit_vip_sessions()` silently quits nothing.
The result: when a test **skips or crashes before** its UI cleanup step, its
session is orphaned permanently, and orphans accumulate across runs. A large
backlog of orphaned sessions is a plausible contributor to resource pressure
(e.g. a session abnormally exiting on suspend).

## Goal

Add a **UI-based fallback** that quits orphaned VIP-named sessions when the
session API is unreachable, so cleanup works on deployments where the API path
is absent — without adding cost on deployments where the API works.

Non-goals: changing `quit_vip_sessions`' contract; an end-of-run browser launch;
any "Quit All" behavior; fixing the API path itself.

## Design

Three focused units.

### 1. API-reachability signal (client)

`WorkbenchClient.sessions_api_reachable() -> bool`

- Performs a lightweight `GET /api/sessions`.
- Returns `True` iff the response status is `< 400` (the API is present), else
  `False`. Returns `False` on any transport exception.
- This is the gate that distinguishes "API present" from "absent". It does not
  modify state.

### 2. UI sweep helper (workbench conftest)

`_quit_vip_sessions_via_ui(page, base_url) -> int`

A sibling to the existing `_quit_vip_sessions_via_cookies`. Using the live,
authenticated Playwright `page`:

- Navigate to `<base_url>/home` and wait for the session table to render.
- Loop, capped at a small maximum iteration count (e.g. 10):
  1. Collect `[aria-label^='select ']` checkboxes (one per session row).
  2. For each, extract the session name (the text after `"select "`) and keep
     only those where `is_vip_session(name)` is true.
  3. If none remain, stop.
  4. Select the matching VIP checkboxes, click `Homepage.QUIT_BUTTON`, then
     dismiss confirmation/force-quit dialogs (`CONFIRM_QUIT`, `FORCE_QUIT`,
     `CONFIRM_FORCE_QUIT`) best-effort.
  5. Reload the homepage and re-check.
- Returns the number of sessions for which a quit was issued.

Safety:
- Only ever clicks **VIP-named** checkboxes (validated with the existing
  `is_vip_session` predicate). Never uses `QUIT_ALL_BUTTON`.
- Wrapped so it **never raises** — a cleanup helper must not fail the test that
  triggered it. All Playwright errors are caught and ignored.

The VIP-name filter is extracted as a small pure helper
(`_vip_names_from_select_labels(labels: list[str]) -> list[str]`) so it can be
unit-tested without a browser.

### 3. Gated hook (per-test `_cleanup_sessions`)

After the existing cookie/API sweep in `_cleanup_sessions`:

- Compute API reachability **once per session**, cached on the session-scoped
  `_wb_cleanup_state` dict (key `"api_reachable"`). This costs a single extra
  `GET` for the whole run, not one per test.
- If the API is **not** reachable, run `_quit_vip_sessions_via_ui(page, base_url)`.
- If the API is reachable, do nothing extra — the UI path is never taken, so
  there is zero added cost on healthy deployments.

Reachability is checked with a scratch cookie-authenticated client, mirroring
`_quit_vip_sessions_via_cookies` (helper:
`_session_api_reachable_via_cookies(base_url, cookies, *, insecure, ca_bundle) -> bool`).

## Testing

Following the repo convention (selftests cover pure pieces; live Playwright
flows run against a real deployment):

Selftests (`selftests/`, no browser):
- `sessions_api_reachable()` returns `True` for a 200 and `False` for a 404,
  using an `httpx.MockTransport`.
- `_vip_names_from_select_labels()` keeps `"VIP test_jobs.py - gw0-1"` and
  `"_vip_cap_Small_0"`, and drops `"my real session"` and labels without the
  `"select "` prefix.

Live (real deployment, not in CI):
- The actual navigate/select/Quit/confirm click-through is exercised by running
  the Workbench suite against a deployment whose API path is absent.

## Files touched

- `src/vip/clients/workbench.py` — add `sessions_api_reachable`.
- `src/vip_tests/workbench/conftest.py` — add `_vip_names_from_select_labels`,
  `_quit_vip_sessions_via_ui`, `_session_api_reachable_via_cookies`; hook the
  fallback into `_cleanup_sessions` with reachability cached on `_wb_cleanup_state`.
- `selftests/` — new selftests for the reachability method and the name filter.
