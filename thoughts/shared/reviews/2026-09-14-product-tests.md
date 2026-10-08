# Review: product-tests

## Summary

The seven documented categories (`prerequisites`, `package_manager`, `connect`, `workbench`, `cross_product`, `performance`, `security`) share one step-naming convention cleanly — first-person `I ...` for `@when`, business language throughout, no leaked selectors in feature text — and the whole suite collects with zero missing-step or orphan-step errors. The real drift is beneath that surface: four of the eight actual category directories (`package_manager`, `performance`, `security`, `config_hygiene` — an eighth, undocumented category) never use the `attest.not_applicable`/`attest.unproven` helpers and rely entirely on bare `pytest.skip`, and in one case (`security/test_https.py`) that bare skip fires on exactly the "asked to check, could not" scenario the design's error-handling rules say should be `attest.unproven` — a broken TLS certificate can pass a security suite silently. Playwright timeout literals also drift: `workbench/conftest.py` and `package_manager/pages/ui.py` establish scaled, named `TIMEOUT_*` constants, but `connect/test_auth.py` and two sites in `workbench/test_session_idle.py` hardcode literal millisecond values instead. The highest-severity finding is a broad `except Exception` in `workbench/test_publish_to_connect.py` that converts any failure while waiting for VS Code to load into a "not installed" skip, which is the precise failure mode issue #616 exists to close.

## Findings

### `except Exception` around an IDE-load wait masks real failures as a skip
Severity: high
Evidence: src/vip_tests/workbench/test_publish_to_connect.py:318-324 `except Exception:\n        pytest.skip(\n            "VS Code did not load within timeout — "\n            "the IDE may not be installed on this Workbench instance"\n        )`
Why it matters to a newcomer: The same file narrows to `except (PlaywrightTimeoutError, PlaywrightError)` three lines above (line 296) for an equivalent wait, so a reader sees both the correct pattern and its violation in one file. A locator typo, a Playwright API change, or a genuine product bug inside `wait_for` all report as "IDE not installed" here, and the run stays green. This is not a triaged file in `selftests/test_skip_triage.py`, so no guard currently catches it.
Proposed fix: Narrow the except clause to `PlaywrightTimeoutError` (matching the sibling pattern at line 296), and let any other exception propagate so pytest records the real failure.
Proposed PR: product-tests-broad-except-skip (files: src/vip_tests/workbench/test_publish_to_connect.py)

### TLS certificate verification failure reported as an ordinary skip, not `attest.unproven`
Severity: high
Evidence: src/vip_tests/security/test_https.py:137-140 `pytest.skip(\n                f"Could not verify TLS certificate for {product} at {pc.url}: {exc}. "\n                + _CERT_TRUST_HINT\n            )`
Why it matters to a newcomer: AGENTS.md defines `attest.unproven` as exactly this case — "VIP was asked to check something and could not" — and says it should fail the run (exit code 6) unless `--allow-unproven` is passed, specifically so an unverified deployment cannot report itself as passing (issue #616, quoted verbatim in AGENTS.md). A deployment with a broken or self-signed certificate that the operator never intended currently passes this security check silently instead of failing loud or requiring an explicit override.
Why it matters to a newcomer (cont.): `security/test_https.py` has zero `attest.*` calls anywhere in the file (confirmed via `git grep -c 'attest\.' src/vip_tests/security/test_https.py`), so this is not an isolated oversight but reflects the whole file never having adopted the helper.
Proposed fix: Import `vip.attest` and change this site to `attest.unproven(...)` with the same message; audit the file's other four bare skips (lines 48, 52, 116) for the same not_applicable-vs-unproven judgment call rather than converting them mechanically.
Proposed PR: product-tests-skip-style-security-config (files: src/vip_tests/security/test_auth_policy.py, src/vip_tests/security/test_https.py, src/vip_tests/config_hygiene/test_secrets.py)

### `kubernetes_client` fixture is unused by its documented consumer; the K8s capacity test rebuilds it
Severity: high
Evidence: src/vip/fixtures.py:210-219 `def kubernetes_client(vip_config: VIPConfig) -> KubernetesClient | None:\n    ...\n    try:\n        return KubernetesClient(namespace=k8s_cfg.namespace)\n    except Exception:\n        return None`
Evidence: src/vip_tests/workbench/test_session_capacity_k8s.py:135-143 `@given("the Kubernetes cluster is configured", target_fixture="k8s_client")\ndef k8s_cluster_configured(vip_config) -> KubernetesClient:\n    k8s_cfg = vip_config.workbench.kubernetes\n    if not k8s_cfg.is_configured:\n        ...\n        return KubernetesClient(namespace=k8s_cfg.namespace)`
Evidence: examples/_shared/AGENTS.md:90 `` `kubernetes_client` | `KubernetesClient \| None` | Read-only Kubernetes client for session-capacity probes. ``
Why it matters to a newcomer: `git grep -rn 'kubernetes_client' src/vip_tests` returns zero hits. The fixture is registered globally (available to every collected test, including extensions) and its own docstring and the extension-facing `AGENTS.md` both say it exists for "session-capacity probes," but the one test file that does K8s session-capacity work never requests it — it constructs its own `KubernetesClient` in a local step instead, with different error handling (the fixture silently returns `None` on any construction exception; the local step lets a construction failure propagate). A newcomer reading the fixture inventory in `examples/_shared/AGENTS.md` will look for this fixture in `test_session_capacity_k8s.py` and not find it.
Proposed fix: Do not merge the two code paths mechanically — the fixture's swallowed `except Exception: return None` and the step's un-guarded construction have different failure semantics, and picking one changes test behavior on a construction error, which is out of scope here. Instead, correct the documentation and leave a comment at the local step naming why it does not reuse the fixture (its own skip message needs the specific `k8s_cfg.namespace` context the fixture discards).
Proposed PR: product-tests-k8s-fixture-inventory-doc (files: examples/_shared/AGENTS.md, src/vip_tests/workbench/test_session_capacity_k8s.py)

### Named, scaled timeout constants are the convention; four sites hardcode literal milliseconds instead
Severity: medium
Evidence: src/vip_tests/workbench/conftest.py:244-261 defines `TIMEOUT_QUICK = int(5_000 * timeout_scale())`, `TIMEOUT_DIALOG = int(10_000 * timeout_scale())`, `TIMEOUT_PAGE_LOAD = int(15_000 * timeout_scale())`, etc. — the target convention, also followed by src/vip_tests/package_manager/pages/ui.py:22-39.
Evidence: src/vip_tests/connect/test_auth.py:37 `page.wait_for_url(lambda url: "/__login__" not in url, timeout=10000)`
Evidence: src/vip_tests/connect/test_auth.py:64 `page.wait_for_selector("body", timeout=10000)`
Evidence: src/vip_tests/workbench/test_session_idle.py:202 `rstudio_eval(page, "invisible(NULL)", timeout=15_000)`
Evidence: src/vip_tests/workbench/test_session_idle.py:240 `expect(suspended).to_be_visible(timeout=5_000)`
Why it matters to a newcomer: `VIP_TIMEOUT_SCALE` (documented in `src/vip/timeouts.py`) is meant to multiply every genuine operation timeout — a slow CI runner or a deliberately-throttled deployment can scale every wait at once. These four sites don't route through `timeout_scale()`, so they stay fixed regardless of the env var, while every other Playwright wait in the same files (`test_session_idle.py` imports and uses `TIMEOUT_PAGE_LOAD`, `TIMEOUT_DIALOG`, etc. on the surrounding lines) does scale. `connect/test_auth.py` has no local timeout constants at all — it's the only UI-driving file in `connect/` and never adopted the pattern `workbench` and `package_manager` established.
Proposed fix: In `test_session_idle.py`, replace `15_000`/`5_000` with the closest matching existing constant (`TIMEOUT_PAGE_LOAD` and a new or existing 5s constant) already imported in that file. In `connect/test_auth.py`, add one module-level `_TIMEOUT_LOGIN_REDIRECT = int(10_000 * timeout_scale())` (or import `scaled`) and use it at both sites.
Proposed PR: product-tests-connect-auth-hardening (files: src/vip_tests/connect/test_auth.py) — bundled with the next finding since both touch the same file; product-tests-timeout-constants-workbench (files: src/vip_tests/workbench/test_session_idle.py)

### Bare `pytest.skip` is the only skip style in four of eight categories
Severity: medium
Evidence: `package_manager`, `performance`, `security`, `config_hygiene` have zero `attest.not_applicable`/`attest.unproven` calls between them, confirmed via `git grep -c 'attest\.not_applicable(\|attest\.unproven(' src/vip_tests/<category>` for each — while `prerequisites`, `connect`, `cross_product`, `workbench` mix bare `pytest.skip` with 4, 11, 10, and 28 `attest.*` calls respectively.
Evidence (representative, package_manager): src/vip_tests/package_manager/test_binary_packages.py:79 `pytest.skip("No CRAN repository configured in Package Manager")`
Evidence (representative, performance): src/vip_tests/performance/test_load.py:42 `pytest.skip("Connect API key is not configured")`
Evidence: full list via `git grep -n 'pytest\.skip(' src/vip_tests/package_manager src/vip_tests/performance src/vip_tests/security src/vip_tests/config_hygiene` (43 sites total: 19 package_manager, 16 performance, 5 security, 3 config_hygiene).
Why it matters to a newcomer: AGENTS.md is explicit that a bare skip "behaves like `not_applicable`" and asks authors to "prefer the explicit helper so the next reader does not have to infer which one you meant." Most of these 43 sites genuinely are the not_applicable case (product/feature not configured — e.g. `test_ui.py:181`'s version gate is a clean example), so converting them is a labeling change, not a behavior change. A few are not (see the `security/test_https.py` finding above and `performance/test_login_load_times.py:54`, which skips on network unreachability that VIP was asked to measure and could not — arguably `attest.unproven`, though the file's own comment argues reachability is covered elsewhere).
Proposed fix: Add `from vip import attest` and convert each not-configured skip to `attest.not_applicable(...)`; flag the ambiguous ones (like the login-load-times unreachability skip) for a judgment call rather than converting on autopilot.
Proposed PR: product-tests-skip-style-package-manager (files: src/vip_tests/package_manager/test_authenticated_repos.py, test_binary_packages.py, test_private_repos.py, test_repos.py, test_ui.py); product-tests-skip-style-performance (files: src/vip_tests/performance/test_load.py, test_login_load_times.py, test_package_install_speed.py, test_resource_usage.py, test_user_simulation.py) — depends on: product-tests-skip-style-security-config resolving the classification question for the analogous reachability skip first, so both files apply the same judgment.

### Connect's only UI login step fills the form with no visibility wait
Severity: medium
Evidence: src/vip_tests/connect/test_auth.py:49-50 `page.fill("[name='username'], #username", test_username)\n    page.fill("[name='password'], #password", test_password)`
Why it matters to a newcomer: Every comparable Workbench interaction in this codebase precedes a fill/click with an explicit `expect(...).to_be_visible(timeout=TIMEOUT_X)` (e.g. `workbench/test_session_idle.py:174-179`, `workbench/test_packages.py:100-101`). `connect/test_auth.py` has no such wait before either fill call and relies solely on Playwright's default 30s actionability polling, which is not configurable per-call here and not visible to a reader scanning for the timeout budget. It is also the file where the immediately preceding step (`navigate_to_login`) just called `page.goto`, so a slow-loading login form is the exact scenario the wait would guard against.
Proposed fix: Add `expect(page.locator("[name='username'], #username")).to_be_visible(timeout=...)` before the first fill, using the same constant introduced for this file in the timeout finding above.
Proposed PR: product-tests-connect-auth-hardening (files: src/vip_tests/connect/test_auth.py)

### Duplicated best-effort cleanup swallows every exception with no tolerance comment
Severity: medium
Evidence: src/vip_tests/workbench/test_session_capacity.py:270-274 `try:\n            expect(row).to_be_hidden(timeout=TIMEOUT_DIALOG)\n        except Exception:\n            pass`
Evidence: src/vip_tests/workbench/test_session_capacity_k8s.py:367-371 (identical four lines)
Evidence: src/vip_tests/workbench/test_jobs.py:91-92 `except Exception:\n        pass`
Evidence: src/vip_tests/workbench/test_runtime_versions.py:173-174 `except Exception:\n        pass`
Why it matters to a newcomer: Sibling cleanup blocks in the same package explain themselves — `test_ide_launch.py:107` has `# Best-effort cleanup — don't mask the original failure/skip.` and `test_chronicle.py:142` has the same comment verbatim — but these four sites catch the same broad exception with no comment at all. The design doc's own rule for wave 2 (`except Exception` survives "only ... [with] a one-line comment naming what is being tolerated and why") isn't met here, and the design doc plans to enable `BLE001` in CI, which will flag these 49 sites across `src/vip_tests` (see `uv run ruff check --select BLE001 src/vip_tests`) without distinguishing the commented ones from these.
Proposed fix: Add the same one-line comment used in `test_ide_launch.py`/`test_chronicle.py` to these four sites; no behavior change.
Proposed PR: product-tests-cleanup-except-comment (files: src/vip_tests/workbench/test_session_capacity.py, test_session_capacity_k8s.py, test_jobs.py, test_runtime_versions.py)

### `config_hygiene` is an eighth category, undocumented in AGENTS.md
Severity: low
Evidence: `find src/vip_tests -maxdepth 1 -type d` lists `config_hygiene` alongside the seven categories AGENTS.md names in its "Product tests" section (lines 63-73), which does not mention `config_hygiene`.
Evidence: AGENTS.md:318 does reference `config_hygiene/test_secrets` in the CI-workflows section, so the directory is known to the docs, just not counted as a category.
Why it matters to a newcomer: A newcomer reading "these are organized by category" and the seven-row list will not know `config_hygiene/` exists or why it's separate from `security/` (both check auth/secrets-adjacent things). Nothing here suggests it's a mistake — `test_secrets.py`'s docstring in the design doc's own review scope treats it as legitimate — it just isn't in the inventory a newcomer would read first.
Proposed fix: Add `config_hygiene` as an eighth row to the category table in AGENTS.md's "Product tests" section, one line, no code change.
Proposed PR: product-tests-category-docs (files: AGENTS.md)

## Proposed PRs

| slug | theme | files | est. changed lines | depends on |
|---|---|---|---|---|
| product-tests-broad-except-skip | narrow a broad except that turns any failure into a false "not installed" skip | src/vip_tests/workbench/test_publish_to_connect.py | ~10 | none |
| product-tests-k8s-fixture-inventory-doc | correct the fixture-inventory doc; comment why the K8s test doesn't reuse it | examples/_shared/AGENTS.md, src/vip_tests/workbench/test_session_capacity_k8s.py | ~15 | none |
| product-tests-connect-auth-hardening | add a visibility wait and a scaled named timeout to the Connect login fill | src/vip_tests/connect/test_auth.py | ~20 | none |
| product-tests-timeout-constants-workbench | replace two literal-ms Playwright timeouts with the file's existing named constants | src/vip_tests/workbench/test_session_idle.py | ~10 | none |
| product-tests-cleanup-except-comment | add the sibling-file tolerance comment to four uncommented broad-except cleanup blocks | src/vip_tests/workbench/test_session_capacity.py, test_session_capacity_k8s.py, test_jobs.py, test_runtime_versions.py | ~20 | none |
| product-tests-skip-style-security-config | classify and convert bare skips to attest.unproven/not_applicable, including the TLS-verification-failure misclassification | src/vip_tests/security/test_auth_policy.py, test_https.py, src/vip_tests/config_hygiene/test_secrets.py | ~60 | none |
| product-tests-skip-style-package-manager | convert bare not-configured skips to attest.not_applicable | src/vip_tests/package_manager/test_authenticated_repos.py, test_binary_packages.py, test_private_repos.py, test_repos.py, test_ui.py | ~200 | none |
| product-tests-skip-style-performance | convert bare skips to attest.not_applicable/unproven, judgment call on the reachability skip | src/vip_tests/performance/test_load.py, test_login_load_times.py, test_package_install_speed.py, test_resource_usage.py, test_user_simulation.py | ~150 | product-tests-skip-style-security-config |
| product-tests-category-docs | document config_hygiene as an eighth category | AGENTS.md | ~5 | none |

## Not findings

- Feature/step drift: `uv run pytest src/vip_tests/ --collect-only -q` collects cleanly (5/139 selected, 134 correctly deselected for missing config, zero collection errors); a five-feature sample (`prerequisites/test_versions`, `connect/test_chronicle`, `workbench/test_data_sources`, `security/test_https`, `cross_product/test_resources`) matched every Gherkin step to a step definition.
- `security/test_https.feature`'s `Given <product> is configured in vip.toml` looked like a missing step definition at first (no local `@given` matches that text in `test_https.py`) — it isn't: this exact phrase is a synthesized auto-skip gate handled specially in `src/vip/plugin.py` (see the comments at plugin.py:682 and :731-737) and defined once per product in `src/vip/fixtures.py`, not per test file. This is a deliberate shared mechanism, not drift.
- The `@if_applicable` feature-tag (binary configured/not-configured auto-skip) and the in-step `attest.not_applicable`/`attest.unproven` helpers (finer-grained runtime checks) are two different, complementary layers, not competing conventions — no finding there.
- `performance_config` and `email_enabled` are defined in `src/vip/fixtures.py` but consumed by exactly one category each (`performance`, `connect`). This looks like a placement mismatch but isn't: AGENTS.md documents that these must stay plugin-registered rather than move to a category `conftest.py`, because `conftest.py` fixtures are scoped by directory ancestry and become invisible to extension directories loaded via `--vip-extensions` (issue #609). Single-category use today doesn't make the placement wrong.
- Selector style (`locator()` vs `get_by_role()`/`get_by_text()`) is overwhelmingly `locator()` with page-object constants (`Homepage.SOMETHING`) across every category that drives a browser; no file breaks from this to raw role/text selectors in a way that reads as drift rather than a one-off.
