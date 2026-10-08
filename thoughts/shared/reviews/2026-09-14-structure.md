# Review: structure

## Summary

The four files are legitimately god-modules, but the call graph inside each one is more coherent than the line count suggests: `auth.py` splits cleanly along cache / browser-launch / SSO-navigation / API-key-minting lines, `cli.py` already delegates to `vip.install`/`vip.clients` sub-packages and just needs its dispatch functions relocated, and `plugin.py` is one long, linear pytest-hook pipeline. The design doc's proposed layouts are directionally right but contain three factual errors that would send an implementer down the wrong path: it names a Typer app that does not exist (VIP's CLI is `argparse`), it proposes per-product auth modules (`connect.py`/`workbench.py`/`packagemanager.py`) for two functions that are single cross-product orchestrators with zero Package Manager logic to move, and it proposes an IDE-based fixture split for `workbench/conftest.py` where no per-IDE fixture logic exists. Separately, a real bug was found in the course of this review: `auth.py` and `workbench/conftest.py` carry two independent copies of `_on_login_page`/`_LOGIN_KEYWORDS` that have already drifted — the `/saml/acs` fix for issue #263 landed in one copy and not the other. Two genuine import cycles (`plugin.py`↔`fixtures.py` via stash keys, `auth.py`↔`idp.py`/`totp.py` via `AuthConfigError`) are papered over with function-local imports and need a pre-split PR each, or the package split will just relocate the cycle instead of resolving it.

## Findings

### Duplicated `_on_login_page` helper has silently drifted from its SAML fix
Severity: high
Evidence: src/vip/auth.py:1329 `_LOGIN_KEYWORDS = ("sign-in", "login", "auth-sign-in", "/saml/acs")`
Evidence: src/vip_tests/workbench/conftest.py:444 `_LOGIN_KEYWORDS = ("sign-in", "login", "auth")`
Evidence: src/vip/auth.py:1332-1345 (docstring: `/saml/acs` is Workbench's SAML Assertion Consumer Service endpoint ... issue #263 diagnostic)
Evidence: src/vip_tests/workbench/conftest.py:447-450 (byte-identical body, no `/saml/acs`, no #263 reference)
Why it matters to a newcomer: two functions with the same name, same body shape, and almost the same constant look like one concept, but they silently diverged the moment someone fixed a bug in only one copy. A newcomer fixing a similar SAML timing issue in `workbench_login` has no signal that the fix already exists next door, incompletely applied.
Proposed fix: this review is structural only — dedupe the two identical function bodies into one shared helper that still takes the keyword tuple as a parameter (so today's two distinct behaviors are preserved, not changed). File a separate bug report for whether `workbench/conftest.py`'s copy should also recognize `/saml/acs`; that is a behavior change to product tests and out of scope for this program.
Proposed PR: structure-workbench-conftest (files: src/vip_tests/workbench/conftest.py, src/vip/auth.py — or a small shared module both import from)

### Design doc names a Typer app that does not exist in this codebase
Severity: high
Evidence: thoughts/shared/plans/2026-09-14-quality-program-design.md:141 `src/vip/cli/: ... plus app.py holding the Typer app and the single VipError handler.`
Evidence: src/vip/cli.py:5 `import argparse`
Evidence: src/vip/cli.py:1571 `parser = argparse.ArgumentParser(`
Why it matters to a newcomer: an implementer who reads only the design doc will look for a Typer `app = typer.Typer()` object to relocate and find nothing, or worse, treat "introduce Typer" as implied scope — a framework migration nowhere else authorized and far larger than a structural move.
Proposed fix: correct the design doc's `app.py` description to "the `argparse.ArgumentParser` construction and subcommand dispatch currently in `main()`, plus the single `VipError` handler," matching what `main()` (src/vip/cli.py:1567) actually builds.
Proposed PR: structure-cli-package (files: src/vip/cli.py, and the design doc itself as a documentation fix)

### Auth per-product module split has no Package Manager logic and two orchestrators that are not per-product
Severity: high
Evidence: src/vip/auth.py:757-758 `def start_interactive_auth(\n    connect_url: str | None = None,\n    workbench_url: str | None = None,`
Evidence: src/vip/auth.py:970-971 (`start_headless_auth` has the identical `connect_url`/`workbench_url` dual-product shape)
Evidence: `grep -in "packagemanager|package_manager|pm_url" src/vip/auth.py` returns zero hits
Evidence: ruff complexity — `start_interactive_auth` C901 23 (8 args, 25 branches, 89 statements), `start_headless_auth` C901 23 (13 args, 25 branches, 96 statements)
Why it matters to a newcomer: the design doc's `connect.py`, `workbench.py`, `packagemanager.py` "per-product login flows" reads as if each product has its own self-contained login function to relocate. In reality the two biggest, most complex functions in the file each drive *both* Connect and Workbench in one call, and Package Manager has no browser-auth code here at all — there is nothing to put in a `packagemanager.py`.
Proposed fix: drop `packagemanager.py` from the auth split target list. Treat `start_interactive_auth`/`start_headless_auth` as a `flows.py` (or similar) module alongside `sso.py`, not per-product files; only the genuinely Workbench-only helper (`_authenticate_workbench`, its `_on_login_page`/`_wait_for_product_redirect`/`_click_workbench_oidc_confirm` cluster) is truly product-specific and that one is Workbench, not Connect or Package Manager.
Proposed PR: structure-auth-package (files: src/vip/auth.py)

### Workbench conftest split proposal (by IDE, by sessions/jobs/git) does not match the file's actual seams
Severity: high
Evidence: src/vip_tests/workbench/conftest.py:97 `_IDE_MARKERS = ("rstudio", "vscode", "jupyter", "positron")` — the only IDE-aware code in the file, confined to the collection/skip-cascade hook cluster (`_workbench_group_name`, `_record_ide_launch_outcome`, `_ide_extension_skip_reason`, `pytest_collection_modifyitems`, `pytest_runtest_makereport`, L116-279)
Evidence: `grep -in "git_ops|\\bjob\\b|jobs" src/vip_tests/workbench/conftest.py` returns zero hits
Evidence: real clusters from the call graph — login/SSO (L53-115, L767-1055, ~14 names), session-lifecycle wait/assert (L590-766, 9 names), session naming/ownership (L389-446, 5 names), cookie-based cleanup (L1056-1305, 7 names), capacity/profile detection (L280-388, 5 names)
Why it matters to a newcomer: "split fixtures by IDE and by concern (sessions, jobs, git)" describes a file this one is not — there is no per-IDE fixture logic, and jobs/git concerns live elsewhere (this file only touches session lifecycle, login, cleanup, and capacity). Following the design doc's literal proposal would produce near-empty `jobs.py`/`git.py` files and one oversized IDE catch-all.
Proposed fix: split along the five clusters actually present: `login.py` (SSO/login/silent-signin), `sessions.py` (wait/assert/state), `naming.py` (worker-owned session naming — AGENTS.md already requires `current_worker_id`, `vip_session_prefix`, `capacity_session_prefix`, `k8s_session_prefix`, `unique_session_name` to stay together, and `vip.clients.workbench._VIP_OWNER_PATTERNS` must be updated in the same commit if this module moves), `cleanup.py` (cookie-based session cleanup), `capacity.py` (profile detection), and leave the small IDE-launch skip-cascade hooks in `conftest.py` itself or a thin `hooks.py`.
Proposed PR: structure-workbench-conftest (files: src/vip_tests/workbench/conftest.py, src/vip/clients/workbench.py for the `_VIP_OWNER_PATTERNS` cross-reference)

### `vip/workbench_ui.py` (framework) imports Page Objects from `src/vip_tests/` (test layer), inverting the documented layer direction
Severity: high
Evidence: src/vip/workbench_ui.py:36 `from vip_tests.workbench.pages import Homepage, LoginPage`
Evidence: AGENTS.md "Four-layer test architecture" — "each layer only communicates with the one directly below it," with `src/vip/clients/` as Layer 3 (Driver Port) and Playwright/httpx as Layer 4 (Driver Adapter); `src/vip_tests/**` (Layers 1-2) is supposed to depend on `src/vip/`, never the reverse
Why it matters to a newcomer: everything else in `src/vip/` is the framework that `src/vip_tests/` depends on. This one import runs the dependency backwards — the framework's Workbench session-cleanup helper reaches into the test suite's page objects — which means `vip/workbench_ui.py` cannot be imported, or its behavior fully understood, without also loading test-suite code, and any future move of `pages.py` breaks a framework module instead of a test module.
Why it matters to the wave-3 split: any `auth/workbench.py` or `plugin/` module that ends up depending on `workbench_ui.py` inherits this same backwards edge, which will surface as a confusing circular-import error the moment package `__init__.py` files start eagerly importing their submodules.
Proposed fix: this is out of scope to fix here (it is not one of the four files/dirs in scope, and moving `Homepage`/`LoginPage` is a behavior-neutral file move, not a rename), but the backlog should record it as a pre-wave-3 finding: either move `Homepage`/`LoginPage` into `vip/clients/` or a new `vip/pages.py`, or move `quit_vip_sessions_via_ui` down into `src/vip_tests/workbench/`. Flag for the coordinator to route to whichever lens owns cross-directory findings, since `workbench_ui.py` itself is outside this review's scope (`src/vip`, `src/vip_tests/**/conftest.py`).
Proposed PR: none in this backlog (file a follow-up finding for the coordinator; `workbench_ui.py` is adjacent to but not inside the reviewed scope)

### `plugin.py` ↔ `fixtures.py` cycle is real and has no home in the proposed plugin/ package
Severity: medium
Evidence: src/vip/plugin.py:42,45,46 `_vip_config_key = pytest.StashKey[VIPConfig]()` / `_auth_session_key = pytest.StashKey[Any]()` / `_auth_mode_key = pytest.StashKey[str]()`
Evidence: src/vip/plugin.py:171 `from vip.fixtures import register as _register_fixtures` (lazy, inside `pytest_configure`)
Evidence: src/vip/fixtures.py:86,106,169,274,283,297,405 — seven separate function-local `from vip.plugin import _auth_session_key` / `_auth_mode_key` / `_vip_config_key` imports
Evidence: src/vip_tests/workbench/conftest.py:30 `from vip.plugin import _auth_session_key` (a third module reaching into the same stash keys)
Why it matters to a newcomer: the underscore prefix reads as "private to `plugin.py`," but these three names are a de facto cross-module contract shared by `plugin.py`, `fixtures.py`, and `workbench/conftest.py`, held together only by import-inside-function-body indirection. The design's `plugin/` package list (`hooks.py`, `markers.py`, `results.py`, `skips.py`, `warnings.py`) has no module named for this, so splitting `plugin.py` as proposed will require re-adding the same lazy-import dance between the new submodules and `fixtures.py`.
Proposed fix: pre-split PR — extract the three `StashKey` constants (and any other stash keys used from more than one module) into a small `vip/plugin/stash.py` (or a top-level `vip/_stash.py`) that both `fixtures.py` and `plugin.py`'s submodules import at module level, with no cycle.
Proposed PR: structure-plugin-package (files: src/vip/plugin.py, src/vip/fixtures.py, src/vip_tests/workbench/conftest.py)

### `auth.py` ↔ `idp.py`/`totp.py` cycle via `AuthConfigError`, invisible in the design's module list
Severity: medium
Evidence: src/vip/idp.py:202,414 `from vip.auth import AuthConfigError` (function-local)
Evidence: src/vip/auth.py:1047 `from vip.idp import SUPPORTED_IDPS, get_idp_strategy`; :1104,1243,1315 `from vip.idp import _log_verbose...` (all function-local)
Evidence: src/vip/totp.py:27 `from vip.auth import AuthConfigError` (function-local)
Evidence: src/vip/auth.py:1036 `from vip import totp` (function-local)
Why it matters to a newcomer: `idp.py` and `totp.py` are not listed as moving into `auth/` except "totp.py moves in" (design doc line 140) — `idp.py` is not mentioned at all, yet it is bidirectionally coupled to `auth.py` through a shared exception type. Whoever implements the split will hit an import error the moment `auth/__init__.py` eagerly imports a submodule that needs `AuthConfigError` from a sibling that isn't built yet.
Proposed fix: pre-split PR — move `AuthConfigError`/`AuthTimeoutError` (src/vip/auth.py:53-64) into a small `vip/auth_errors.py` that `auth.py`, `idp.py`, and `totp.py` all import at top level. Decide explicitly whether `idp.py` moves into the `auth/` package (it is tightly coupled enough to belong there) or stays a sibling module the package imports.
Proposed PR: structure-auth-package (files: src/vip/auth.py, src/vip/idp.py, src/vip/totp.py)

### Connect API-key-minting / URL-scheme cluster in auth.py has no slot in the proposed module list
Severity: medium
Evidence: cluster by call graph — `_httpx_verify`, `_httpx_verify_env_aware`, `_delete_api_key`, `_xsrf_from_page`, `_summarize_cookies`, `_log_mint_cookie_diagnostic`, `_response_text`, `_delete_stale_vip_keys`, `_content_type`, `_probe_server_settings`, `_body_snippet`, `_tls_listener_present`, `resolve_url_scheme`, `_resolve_connect_api_base`, `_create_api_key_via_session` (src/vip/auth.py:1535-2274, ~740 of the file's 2274 lines)
Evidence: src/vip/cli.py:908,1117,1131,1498,1510 — five separate `from vip.auth import resolve_url_scheme` call sites
Evidence: src/vip/fixtures.py:70 `from vip.auth import resolve_url_scheme`
Why it matters to a newcomer: this is roughly a third of the file and doesn't fit "per-product login flow" (`connect.py`) or "cache" or "sso" — it is Connect-specific API-key minting plus general-purpose URL-scheme/TLS-probing utilities consumed well outside any login flow, by `cli.py` and `fixtures.py`.
Proposed fix: split into `auth/apikey.py` (the minting/cookie/XSRF cluster, genuinely Connect-specific) and leave `resolve_url_scheme`/`_tls_listener_present`/the `_normalize_url` family as a candidate for a non-auth home (e.g. `vip/url_resolution.py`) given their consumers outside auth flows — flag this as an open decision for the backlog coordinator rather than a fixed module name.
Proposed PR: structure-auth-package (files: src/vip/auth.py; possibly a new src/vip/url_resolution.py, src/vip/cli.py, src/vip/fixtures.py if the URL-scheme utilities move out of auth entirely)

### `cli.py` report-template helpers are shared by two different proposed command modules
Severity: low
Evidence: src/vip/cli.py:1173 `_resolve_scaffold_source` calls `_ensure_report_templates` (defined at cli.py:704, part of the `report.py`-bound cluster with `_has_all_report_templates` L675 and `_copy_report_templates` L680)
Why it matters to a newcomer: the design's one-module-per-command-group cli/ layout implies `scaffold.py` and `report.py` are independent, but `run_scaffold`'s helper reaches into the report-template provisioning cluster to seed a scaffolded extension's report assets.
Proposed fix: keep `_has_all_report_templates`/`_copy_report_templates`/`_ensure_report_templates` in `report.py` and have `scaffold.py` import them, or extract them into a small shared `cli/_report_templates.py` if `scaffold.py` importing from `report.py` reads backwards. Either is a one-line note in the PR body, not a design change.
Proposed PR: structure-cli-package (files: src/vip/cli.py)

## Proposed PRs

| slug | theme | files | estimated changed lines | depends on |
|---|---|---|---|---|
| structure-pre-split-stash-keys | extract shared `pytest.StashKey` constants out of `plugin.py` into a small shared module | src/vip/plugin.py, src/vip/fixtures.py, src/vip_tests/workbench/conftest.py | ~60 | none |
| structure-pre-split-auth-errors | extract `AuthConfigError`/`AuthTimeoutError` into `vip/auth_errors.py` to break the auth.py↔idp.py↔totp.py cycle | src/vip/auth.py, src/vip/idp.py, src/vip/totp.py | ~40 | none |
| structure-auth-package | split auth.py into a package: cache, browser launch, sso/navigation, flows (interactive/headless orchestrators), apikey minting; fold idp.py in or wire it as a sibling; drop the packagemanager.py target | src/vip/auth.py, src/vip/idp.py, new src/vip/auth/*.py, src/vip/cli.py, src/vip/fixtures.py, src/vip_tests/workbench/conftest.py (import path updates) | large (pure move, live-gated) | structure-pre-split-auth-errors |
| structure-cli-package | split cli.py into one module per command group per design, corrected to argparse (not Typer); consolidate report-template helper sharing between report.py/scaffold.py | src/vip/cli.py, new src/vip/cli/*.py, thoughts/shared/plans/2026-09-14-quality-program-design.md (fix Typer wording) | large (pure move, live-gated) | none |
| structure-plugin-package | split plugin.py into hooks/markers/results/skips/warnings per design, with shared stash keys already extracted | src/vip/plugin.py, new src/vip/plugin/*.py, src/vip/fixtures.py | large (pure move, live-gated) | structure-pre-split-stash-keys |
| structure-workbench-conftest | split workbench/conftest.py into login/sessions/naming/cleanup/capacity modules (not by-IDE), update `_VIP_OWNER_PATTERNS` cross-reference, dedupe `_on_login_page` with auth.py's copy (structural only, no behavior change) | src/vip_tests/workbench/conftest.py, src/vip/clients/workbench.py, src/vip/auth.py | large (pure move, live-gated) | none |

## Not findings

- No duplicated fixtures across `src/vip_tests/**/conftest.py` and `src/vip/fixtures.py` — fixture names are unique per file; `src/vip/fixtures.py` owns the generic ones, `workbench/conftest.py` and `src/vip_tests/conftest.py` own only their directory-scoped ones, consistent with the documented reason in AGENTS.md for keeping `src/vip_tests/conftest.py`'s cleanup fixtures directory-scoped.
- No private helper (`^def _` in `src/vip/*.py`) is called from exactly one external module in a simple "should move next to its caller" way — every genuine cross-module private dependency found (stash keys, `AuthConfigError`) is used from two or more modules, which is a shared-contract problem (see findings above), not a misplaced helper.
- `src/vip/clients/` and `src/vip/install/` are already precedent sub-packages that `cli.py` calls into exclusively through lazy, function-local imports — the cli.py split can follow this existing, working pattern rather than invent a new one.
- Ruff's own complexity flags (`C901`, `PLR0912`, `PLR0913`, `PLR0915`) land exactly on the functions this review independently identified as split/extraction targets (`start_interactive_auth`, `start_headless_auth`, `run_verify`, `_generate_temp_config`, `pytest_configure`, `workbench_login`) — no divergence between the two signals worth flagging separately; leave the rule-family counts to the typing-lint lens.
