# VIP quality program: wave 2 approval package

For Ian's batch approval per the design doc ("Approvals: Batch per wave. Ian approves the full list of PR titles and bodies once per wave. Agents use that text verbatim."). Covers wave 2 (error handling), 11 PRs, from `thoughts/shared/plans/2026-09-14-quality-program-backlog.md` rows 2.1-2.11, in dependency order.

`errors-hierarchy` (2.1) is first; every other error-handling row except the two independent product-test fixes (2.10, 2.11) depends on it, because it introduces `VipError` and the CLI's single exit handler that the narrowing PRs raise into.

## PR title rules

Copied from `.github/workflows/pr-title.yml`, which `amannn/action-semantic-pull-request` enforces on every PR:

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

- Format: `<type>: <description>` or `<type>(<scope>): <description>`. Scope is optional (`requireScope: false`).
- The subject after the type must not be empty (`subjectPattern: ^.+$`).
- A `!` after the type or scope marks a breaking change — not used anywhere in this wave.

Additional rules from AGENTS.md's "PR titles" section, not enforced by the workflow but required by repo convention:

- Do not capitalize the first letter of the description (identifiers like `VipError` keep their casing).
- Do not end the description with a period.
- Keep the title under 70 characters.

## 2.1 errors-hierarchy

Branch: errors-hierarchy
Title: feat(errors): introduce the VipError hierarchy
Body:
Adds `src/vip/errors.py` with `VipError` (carrying an `exit_code`) and five subclasses — `ConfigError`, `AuthError`, `ProductUnreachableError`, `InstallError`, `ReportError` — and reconciles them with the exception classes that already exist rather than replacing them: the error-handling review found `auth.py` already defines `AuthConfigError(ValueError)` and `AuthTimeoutError(AuthConfigError)`, each with three independent catch sites across `cli.py`/`plugin.py` and fifteen pinned selftests. `AuthConfigError` is re-parented onto `AuthError` (kept as the concrete class other code already imports, not replaced) so no existing raise/except/selftest site changes behavior. Moves `AuthConfigError`/`AuthTimeoutError` out of `auth.py` into `errors.py` to break the auth↔idp↔totp import cycle the structure review flagged, with both names re-exported from `auth.py` for existing call sites. Adds a single exit handler wrapping the `args.func(args)` dispatch at `cli.py:2050` (the review corrected the design doc's assumption of a Typer `app` — `cli.py` is argparse, and this dispatch call is the one place to catch `VipError` and call `sys.exit(exc.exit_code)`); this PR only introduces the handler; it does not yet migrate the 37 existing `sys.exit` call sites, that is 2.2.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; adds `selftests/test_errors.py` covering the hierarchy's exit codes and the `AuthConfigError` re-parenting.

Files: src/vip/errors.py, src/vip/auth.py, src/vip/cli.py, src/vip/plugin.py, src/vip/idp.py, src/vip/totp.py, selftests/test_errors.py
Findings: error-handling#Design doc's error-hierarchy premise ignores an existing exception class; error-handling#`cli.py` is argparse, not Typer; error-handling#Failure vocabulary has no mapping to the design's proposed VipError subclasses; structure#`auth.py` ↔ `idp.py`/`totp.py` cycle via AuthConfigError
Depends on: none (first PR in wave 2; every other error-handling row below depends on it)

## 2.2 errors-cli-single-handler

Branch: errors-cli-single-handler
Title: refactor(cli): route sys.exit calls through one handler
Body:
Replaces the 37 `print(f"Error: ...", file=sys.stderr); sys.exit(1)` call sites in `cli.py` with `raise <VipError subclass>(...)`, so the single handler `errors-hierarchy` added at the `args.func(args)` dispatch does the printing and exit-code selection instead of each command function doing it independently. Also removes the two duplicated `except AuthConfigError` translations at `cli.py:1364` that convert it to the same printed string the new handler now produces directly; `plugin.py`'s two `except AuthConfigError: raise pytest.UsageError(...)` sites are intentionally left as-is, since pytest owns its own exit mechanism there. Each `sys.exit` site is mapped to the `VipError` subclass whose failure mode matches it (`ConfigError` for CLI-flag/config validation, `ReportError` for the Quarto-not-found case at `cli.py:865`, etc.) — that mapping is included below rather than re-derived by review, per the error-handling review's recommendation.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; existing CLI selftests (`test_cli_*.py`) continue to assert the same exit codes and printed messages, now produced by the handler instead of by each call site.

Files: src/vip/cli.py
Findings: error-handling#No single exit handler exists yet: 37 sys.exit calls and three duplicated AuthConfigError translations
Depends on: errors-hierarchy (shares src/vip/cli.py; needs VipError and the handler to exist first)

## 2.3 errors-narrow-auth

Branch: errors-narrow-auth
Title: fix(auth): narrow broad excepts to concrete exception types
Body:
Narrows `auth.py`'s ~40 `BLE001`-marked `except Exception` sites to the concrete types the file already imports and uses correctly elsewhere (`PlaywrightError`, `PlaywrightTimeoutError`, `OSError`, `ValueError`, `AttributeError`), per the error-handling review's finding that the file catches the same Playwright calls (`page.url`, `page.click`, `page.wait_for_timeout`, `browser.close`) both narrowly and broadly depending on the site, with no way for a newcomer to tell which is deliberate. Includes the two specific findings called out by review: `auth.py:528`'s cache-metadata parse narrows to `(OSError, ValueError, AttributeError)` to match its sibling three lines away at `auth.py:255`, and the ~30 polling/cleanup-loop sites narrow to `PlaywrightError`. Every site that stays broad (the two already-documented "never raises" cleanup paths noted in "Not findings") keeps its existing comment unchanged. This is a narrowing-only PR: no `# noqa: BLE001` marker is removed without a concrete type replacing it, and none of the ~40 sites change control flow.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; auth selftests (`test_auth.py`, `test_auth_headless.py` and friends) continue to pass unchanged since narrowing a catch clause that already only observes these exception types in practice does not change behavior.

Files: src/vip/auth.py
Findings: error-handling#`auth.py` cache-metadata parse silently swallows more than its sibling three lines away; error-handling#`auth.py` polling and cleanup loops swallow silently despite the concrete exception type being imported in the same file
Depends on: errors-hierarchy (shares src/vip/auth.py; narrows onto the same file the hierarchy PR moves AuthConfigError out of)

## 2.4 errors-narrow-clients

Branch: errors-narrow-clients
Title: fix(clients): raise instead of returning silent sentinels
Body:
Replaces the undocumented failure sentinels in `clients/connect.py` and `clients/workbench.py` with a raised `ProductUnreachableError`. The highest-severity instance: `clients/connect.py:269` returns `[]` on any exception from the tag-lookup call that feeds `cleanup_vip_content()`, indistinguishable from "there really is nothing tagged to clean up" — a newcomer debugging why cleanup silently no-ops has no signal the lookup itself failed. `clients/workbench.py` compounds this with three different undocumented sentinels for the same "API call failed" case across four sibling methods (`-1`, `False`, a bare `return`, and one already-documented `break`); all three undocumented ones become a raised `ProductUnreachableError`, and the one already-documented site (`workbench.py:332`, "Connection error, non-JSON body, etc. — give up this run.") is left as the reviewed example of the pattern, unchanged. Callers (`cleanup_vip_content` and the Workbench cleanup sweep) are updated to catch `ProductUnreachableError` explicitly where a failed API call should abort rather than silently continue, per the design's rule that test code does not catch `VipError` but framework cleanup code may.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; this is a behavior change for the three undocumented sentinel sites (a failed lookup now raises instead of returning a value indistinguishable from "nothing to do") — selftests covering `cleanup_vip_content` and the Workbench sweep are updated to assert the raise.

Files: src/vip/clients/connect.py, src/vip/clients/workbench.py, src/vip/clients/packagemanager.py
Findings: error-handling#`clients/connect.py` returns an empty list on any failure, indistinguishable from "nothing to clean up"; error-handling#`clients/workbench.py` uses three different undocumented sentinels for the same failure mode
Depends on: errors-hierarchy (needs ProductUnreachableError to exist)

## 2.5 errors-narrow-proxy

Branch: errors-narrow-proxy
Title: fix(proxy): narrow httpx.URL parse sites to the concrete exception
Body:
Narrows `proxy.py`'s `httpx.URL(...)` parsing call sites (resolving `NO_PROXY`/`HTTP_PROXY` patterns and building the per-scheme mount map) from `except Exception` to the concrete exception httpx raises on a malformed URL, per the error-handling review's BLE001 enumeration. `proxy.py` has no other failure modes at these sites — the parse either succeeds or httpx rejects the string — so this is a mechanical narrowing with no behavior change for a well-formed environment and an unchanged (still surfaced, not swallowed) failure for a malformed one.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; `selftests/test_proxy.py` and `selftests/test_scheme_resolution_proxy.py` continue to pass unchanged.

Files: src/vip/proxy.py
Findings: error-handling review, BLE001 aggregate enumeration (no dedicated write-up)
Depends on: errors-hierarchy (shares the wave's narrowing convention; no direct file overlap)

## 2.6 errors-narrow-install

Branch: errors-narrow-install
Title: docs(install): confirm and document remaining broad excepts
Body:
Reviews the remaining undocumented `BLE001` sites in `install/playwright.py` and `install/runner.py`. `install/playwright.py:55`'s `except Exception: return None` is already fully explained by its own docstring ("Returns None if playwright cannot be imported... callers should treat that as revision unknown") per the error-handling review's "Not findings" section, so it is left as-is with a one-line comment added at the except site itself (the docstring already exists but the except clause had none). `install/runner.py:180`'s pre-existing `# noqa: BLE001` (the only one in the repository predating wave 1's ratchet) is confirmed still necessary — it is a documented best-effort chained-cleanup warning — and is left unchanged as the worked example the review flagged. No control-flow changes in this PR.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; comment-only change.

Files: src/vip/install/playwright.py, src/vip/install/runner.py
Findings: error-handling review, BLE001 aggregate enumeration; error-handling#Not findings (install/playwright.py, install/runner.py)
Depends on: errors-hierarchy (wave sequencing only; no file overlap)

## 2.7 errors-narrow-plugin-fixtures

Branch: errors-narrow-plugin-fixtures
Title: fix(fixtures): raise on Kubernetes client construction failure
Body:
Narrows `fixtures.py:219`'s `except Exception: return None` around `KubernetesClient` construction. The review found this fixture already checks `k8s_cfg.is_configured` before the try block, so this broad except is not catching "k8s isn't configured" (already handled) — it is catching a real construction failure (bad kubeconfig, missing credentials, SDK import error) and making it look identical to the unconfigured case, so a test that depends on this fixture silently skips instead of failing loudly on a broken k8s setup. Narrows to the exception types `KubernetesClient.__init__` actually raises (per `clients/kubernetes.py`), and raises a `ConfigError` for the rest so the misconfiguration surfaces instead of masquerading as "not configured."

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; this is a behavior change (a broken k8s config now raises instead of skipping) — the k8s-fixture selftest is updated to assert the raise on a construction failure and `None` only on `is_configured=False`.

Files: src/vip/fixtures.py, src/vip/plugin.py
Findings: error-handling#`fixtures.py` collapses a Kubernetes client construction error into "not configured"
Depends on: errors-hierarchy (needs ConfigError; shares src/vip/plugin.py with errors-hierarchy's re-export)

## 2.8 errors-narrow-workbench-ui

Branch: errors-narrow-workbench-ui
Title: docs(workbench-ui): comment the remaining broad except sites
Body:
`workbench_ui.py`'s `quit_vip_sessions_via_ui` already logs every broad except with `logger.warning` and ends with an always-visible summary — the error-handling review calls this out as the model the rest of the codebase should copy, not a problem. This PR adds the one-line "why" comment the design's BLE001 policy requires to the handful of sites in the same file that log correctly but were never annotated, so every broad except in the file states its reasoning inline rather than relying on the reader inferring it from the surrounding logging. No control-flow changes.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; comment-only change.

Files: src/vip/workbench_ui.py
Findings: error-handling review, BLE001 aggregate enumeration (no dedicated write-up)
Depends on: errors-hierarchy (wave sequencing only; no file overlap)

## 2.9 errors-narrow-product-tests

Branch: errors-narrow-product-tests
Title: fix(vip_tests): narrow remaining broad excepts outside Workbench
Body:
Narrows the remaining `BLE001` sites in the product-test tree outside Workbench (already covered by wave 1's `comments-tests-workbench-cleanup` and 2.10 below): `connect/test_content_deploy.py`, `cross_product/test_resources.py`, `cross_product/test_ssl.py`, `helpers.py`, `performance/test_concurrency.py`, `performance/test_resource_usage.py`, and the two load-test modules `load_engine.py`/`load_users.py`. Each site is narrowed to the concrete exception its surrounding code already implies (`httpx` exceptions for HTTP calls, `PlaywrightError`/`PlaywrightTimeoutError` for browser waits, `OSError` for subprocess/socket probes), matching the pattern `errors-narrow-auth` establishes for `auth.py`. Sites that are genuinely best-effort cleanup (matching the "don't mask the test's real outcome" pattern already documented in `test_ide_launch.py`) get the same one-line comment rather than a narrowed type, since narrowing a deliberately-broad cleanup catch would be a regression, not a fix.

Verified with `uvx ruff@0.15.0 check .`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`.

Files: src/vip_tests/connect/test_content_deploy.py, src/vip_tests/cross_product/test_resources.py, src/vip_tests/cross_product/test_ssl.py, src/vip_tests/helpers.py, src/vip_tests/performance/test_concurrency.py, src/vip_tests/performance/test_resource_usage.py, src/vip/load_engine.py, src/vip/load_users.py
Findings: error-handling review, BLE001 aggregate enumeration (no dedicated write-up)
Depends on: errors-hierarchy (wave sequencing only; no file overlap)

## 2.10 errors-fix-vscode-load-skip

Branch: errors-fix-vscode-load-skip
Title: fix(workbench): stop masking VS Code load failures as a skip
Body:
`test_publish_to_connect.py:318-324` wraps the VS Code IDE-load wait in a bare `except Exception: pytest.skip("VS Code did not load within timeout — the IDE may not be installed...")` — the exact failure mode issue #616 exists to close: an unverified deployment reporting itself as passing. The same file narrows to `except (PlaywrightTimeoutError, PlaywrightError)` three lines above at line 296 for an equivalent wait, so the fix is to match that sibling pattern: narrow to `PlaywrightTimeoutError` for the genuine "IDE not installed" case, and let any other exception propagate as a real test failure instead of a skip. The file is not currently in `selftests/test_skip_triage.py`'s `TRIAGED_FILES` list, so it was invisible to that guard; this PR adds it. This overrides the wave 1 scope line "no product-test behavior change" deliberately, per Ian's 2026-09-14 decision that this specific silent-failure bug ships as a fix rather than staying backlog-only.

Verified with `uv run pytest src/vip_tests/ --collect-only -q` (collection unaffected) and `uv run pytest selftests/test_skip_triage.py -v`; product-test behavior itself cannot be verified in CI (no live Workbench), so this also gets a GitHub issue documenting the manual verification needed against a real deployment before the next live VIP run.

Files: src/vip_tests/workbench/test_publish_to_connect.py, selftests/test_skip_triage.py
Findings: product-tests#`except Exception` around an IDE-load wait masks real failures as a skip; error-handling#`test_publish_to_connect.py` uses a bare pytest.skip where sibling files already use attest
Depends on: none

## 2.11 errors-fix-tls-verify-unproven

Branch: errors-fix-tls-verify-unproven
Title: fix(security): report TLS verify failure as attest.unproven
Body:
`security/test_https.py:137-140` reports a TLS-certificate-verification failure as an ordinary `pytest.skip`, even though `AGENTS.md` defines `attest.unproven` for exactly this case — "VIP was asked to check something and could not" — specifically so an unverified deployment cannot report itself as passing (issue #616). The file has zero `attest.*` calls anywhere (confirmed via `git grep -c 'attest\.' src/vip_tests/security/test_https.py`), so this converts the one cert-verification site to `attest.unproven(...)` with the same message. Scoped to this one file and this one site per the backlog (the review's broader suggestion to also audit `test_auth_policy.py`/`test_secrets.py`'s other skips is left for a future pass, not bundled here). This also overrides the wave 1 "no product-test behavior change" scope line, per Ian's 2026-09-14 decision.

Verified with `uv run pytest src/vip_tests/ --collect-only -q`; behavior itself (exit code 6 on a real cert failure without `--allow-unproven`) cannot be verified in CI, so this also gets a GitHub issue documenting the manual verification needed against a real deployment with a broken certificate.

Files: src/vip_tests/security/test_https.py
Findings: product-tests#TLS certificate verification failure reported as an ordinary skip, not attest.unproven
Depends on: none
