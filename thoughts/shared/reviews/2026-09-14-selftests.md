# Review: selftests

## Summary

`selftests/` is functionally solid (1951 tests, 15.86s total, nothing over ~4.3s) and its documented drift guards (`test_report_content.py` colors against `styles.css`, `test_scaffold_agents_md.py` inventory against real source, `test_cli_report.py`'s pyproject force-include check) are genuinely independent-source comparisons, not self-referential pins. The two things that matter most for a newcomer: five files are large enough to make "where does the test for X live" a real question (`test_auth.py` at 3464 lines and `test_plugin.py` at 2454 lines dominate, each holding one enormous class — `TestPluginIntegration` alone is ~1085 lines and 98 test methods covering four unrelated subjects), and a handful of substantial helpers (TLS self-signed cert generation, mock-client-with-handler builders) are copy-pasted across two or three files instead of living in `conftest.py`. `pytester` usage is well-scoped: the slow subprocess variant (`runpytest_subprocess`) is reserved for the handful of cases that genuinely need process isolation (directory-ancestry fixture scoping, `--vip-extensions` loading), while the bulk of plugin-integration tests correctly use the faster in-process `runpytest`/`runpytest_inprocess`.

## Findings

### `TestPluginIntegration` bundles four unrelated subjects in one 1085-line class
Severity: high
Evidence: selftests/test_plugin.py:275 `class TestPluginIntegration:`
Evidence: selftests/test_plugin.py:291 `    def test_unconfigured_product_deselected(self, selftest_pytester):` (marker/deselection group starts here)
Evidence: selftests/test_plugin.py:313 `    def test_progress_indicator_recolored_per_line(self, selftest_pytester):` (terminal/progress-output group)
Evidence: selftests/test_plugin.py:558 `    def test_json_report_output(self, selftest_pytester):` (JSON report-field group, run: `grep -n 'def test_json_report' selftests/test_plugin.py`, 13 hits)
Evidence: selftests/test_plugin.py:1214 `    def test_unproven_skip_is_flagged_and_reason_is_clean(self, selftest_pytester):` (attest/skip-classification group)
Why it matters to a newcomer: the class name says "integration" but gives no hint that a change to skip-reason wording, JSON report shape, marker deselection, and terminal color output all live in the same 1000-line block; `grep`-ing for "json_report" still requires scrolling through unrelated deselection and terminal tests to find the class boundary.
Proposed fix: split into `TestMarkerDeselection`, `TestTerminalOutput`, `TestJsonReportFields`, and `TestSkipAttestationReporting`, each in its own file under `selftests/plugin/`, sharing the existing `selftest_pytester` fixture via `selftests/conftest.py`.
Proposed PR: selftests-split-plugin (files: selftests/test_plugin.py, selftests/plugin/test_marker_deselection.py, selftests/plugin/test_terminal_output.py, selftests/plugin/test_json_report.py, selftests/plugin/test_skip_attestation.py, selftests/conftest.py)

### `test_auth.py` at 3464 lines has 28 classes with no file-level grouping
Severity: high
Evidence: selftests/test_auth.py:18 `class TestStartHeadlessAuthValidation:` through selftests/test_auth.py:3386 `class TestRefreshAuthCacheFromStorageState:` (28 classes total, run: `grep -n '^class Test' selftests/test_auth.py`)
Why it matters to a newcomer: the file mixes headless-auth CLI validation, interactive-session polling, URL-scheme resolution, TLS flags, cookie/cache probing, and API-key minting under one filename; a change to `resolve_url_scheme` (selftests/test_auth.py:1468) requires knowing it isn't in `test_scheme_resolution_proxy.py`, a separate file that already exists for a closely related concern.
Proposed fix: split by the `src/vip/auth.py` function each class targets: `test_auth_headless.py` (`TestStartHeadlessAuthValidation`, `TestStartHeadlessAuthPlaywrightErrors`, `TestStartHeadlessAuthSchemeResolutionWiring`, `TestHeadlessAuthTLSFlags`, lines 18-737 + 674-737 + 2656-2765), `test_auth_interactive.py` (`TestSaveAuthCache`, `TestInteractiveAuthSessionCleanup`, `TestStartInteractiveAuthPollLoop`, `TestStartInteractiveAuthSchemeResolutionWiring`, `TestAuthenticateWorkbench`, `TestWaitForProductRedirect*`, `TestClickWorkbenchOidcConfirm`, lines 179-823, 1209-1435), `test_auth_scheme.py` (`TestSchemeResolutionRealCodePath`, `TestResolveUrlScheme`, `TestResolveConnectApiBase`, lines 737-1881 excluding the interactive classes), `test_auth_cache.py` (`TestLoadCachedAuth*`, `TestAuthCachePath`, `TestStaleCacheTriggersReauth`, `TestCachedWorkbenchSessionIsLive`, `TestCookiesFromStorageState`, `TestRefreshAuthCacheFromStorageState`, `TestProbeCookieScoping`, `TestProbeDetailNamesTheEvidence`, lines 1039-1209, 2765-3464), `test_auth_apikey.py` (`TestCreateApiKeyViaSession`, lines 1881-2656). Each lands under 700 lines; a second pass could split `test_auth_cache.py` further since it is still the largest at ~700 lines.
Proposed PR: selftests-split-auth (files: selftests/test_auth.py, selftests/test_auth_headless.py, selftests/test_auth_interactive.py, selftests/test_auth_scheme.py, selftests/test_auth_cache.py, selftests/test_auth_apikey.py)

### TLS test-server helpers are duplicated verbatim across two files
Severity: medium
Evidence: selftests/test_clients_tls.py:35 `def _make_self_signed(certdir: Path) -> tuple[Path, Path]:`
Evidence: selftests/test_auth_tls_e2e.py:34 `def _make_self_signed(certdir: Path) -> tuple[Path, Path]:`
Evidence: selftests/test_clients_tls.py:87 `def _start_tls_server(cert_path: Path, key_path: Path) -> tuple[ThreadingHTTPServer, str]:`
Evidence: selftests/test_auth_tls_e2e.py:93 `def _start_tls_server(cert: Path, key: Path) -> tuple[ThreadingHTTPServer, str]:`
Why it matters to a newcomer: both helpers run `openssl req -x509 -newkey rsa:2048 ...` and wrap a `ThreadingHTTPServer` in an `SSLContext`, ~25 and ~15 lines respectively, differing only in the request handler class passed in; a newcomer fixing an openssl-invocation bug (e.g. a missing `-days` argument) in one copy has no signal that a second copy exists and needs the same fix.
Proposed fix: move both into `selftests/conftest.py` as fixtures/helpers parameterized on the handler class, matching the existing pattern of shared fixtures like `tmp_toml`.
Proposed PR: selftests-dedupe-fixtures (files: selftests/conftest.py, selftests/test_clients_tls.py, selftests/test_auth_tls_e2e.py)

### `_client_with_handler` is duplicated identically for Workbench in two files
Severity: low
Evidence: selftests/test_workbench_cleanup.py:32 `def _client_with_handler(handler) -> WorkbenchClient:`
Evidence: selftests/test_workbench_jupyter_cleanup.py:83 `def _client_with_handler(handler) -> WorkbenchClient:`
Why it matters to a newcomer: the two definitions are byte-identical (construct a `WorkbenchClient`, swap in an `httpx.MockTransport`); a reader who finds one copy has no way to know a second, equally-current copy exists elsewhere.
Proposed fix: move the Workbench variant into `selftests/conftest.py` alongside the existing `_client_with_handler` in `test_connect_cleanup.py` (which targets `ConnectClient` and can stay separate, or be generalized to take the client class).
Proposed PR: selftests-dedupe-fixtures (files: selftests/conftest.py, selftests/test_workbench_cleanup.py, selftests/test_workbench_jupyter_cleanup.py)

### `_repo` dict-builder duplicated in two Package Manager test files
Severity: low
Evidence: selftests/test_pm_ui_target.py:78 `def _repo(name, type_=""):`
Evidence: selftests/test_pm_repo_selection.py:60 `def _repo(name, type_=""):`
Why it matters to a newcomer: trivial (2-line) duplication, but it is the third private helper duplicated across the Package Manager step-test files, suggesting these files split at the wrong seam.
Proposed fix: move into `selftests/conftest.py`.
Proposed PR: selftests-dedupe-fixtures (files: selftests/conftest.py, selftests/test_pm_ui_target.py, selftests/test_pm_repo_selection.py)

### `_ensure_report_templates` tests iterate the same constant they assert against
Severity: low
Evidence: selftests/test_cli_report.py:80 `for name in _REPORT_TEMPLATE_FILES:` inside `test_copies_template_files_into_empty_dir`, asserting `(report_dir / name).is_file()`
Evidence: selftests/test_cli_report.py:107 `for name in _REPORT_TEMPLATE_FILES:` inside `test_partial_template_set_is_not_complete`
Evidence: selftests/test_cli_report.py:159 `for name in _REPORT_TEMPLATE_FILES:` inside `test_unchanged_templates_are_not_rewritten`
Why it matters to a newcomer: these three tests use `_REPORT_TEMPLATE_FILES` both to drive the loop and to check the result, so they cannot catch a bug where the constant itself is wrong or stale (e.g. missing a newly added template file) — only the sibling `test_pyproject_force_include_matches_template_list` (same file, line 118) does that, by checking against the independent `pyproject.toml` force-include list. This is much lower severity than the pattern the design doc warns about, because the thing under test here (file-copy behavior) is genuinely orthogonal to the list's contents, but it is worth a one-line comment noting that `test_pyproject_force_include_matches_template_list` is the test that guards the list's own correctness.
Proposed fix: add a short comment above each of the three loop-based tests pointing to `test_pyproject_force_include_matches_template_list` as the drift guard for the list's contents, so a reader does not mistake the loops for that guard.
Proposed PR: none — comment-only, fold into whichever comments/docstring PR the `comments` lens proposes for `selftests/`.

### `_make_args` and `_make_config` names collide across files with unrelated bodies
Severity: low
Evidence: selftests/test_cli_verify.py:15 `def _make_args(**overrides) -> argparse.Namespace:` (defaults tailored to `run_verify`)
Evidence: selftests/test_cli_status.py:12 `def _make_args(**overrides) -> argparse.Namespace:` (defaults tailored to `run_status`)
Evidence: selftests/test_cli_report.py:21 `def _make_args(**overrides) -> argparse.Namespace:` (defaults tailored to `run_report`)
Evidence: selftests/test_cli_scaffold.py:10 `def _make_args(**overrides) -> argparse.Namespace:` (defaults tailored to `run_scaffold`)
Evidence: selftests/test_cli_cleanup.py:26 `def _make_args(**overrides) -> argparse.Namespace:` (defaults tailored to `run_cleanup`)
Why it matters to a newcomer: these are not duplicates (each builds a different `argparse.Namespace` shape for a different CLI subcommand), but the identical name across five files means a grep for `_make_args` returns five unrelated hits, and `test_cli_status.py` separately defines an unrelated `_make_config` that collides by name (not by body) with `test_performance_steps.py:20`'s `_make_config`.
Proposed fix: rename each to name the subcommand it targets (`_verify_args`, `_status_args`, `_report_args`, `_scaffold_args`, `_cleanup_args`); this is a pure rename, no behavior change.
Proposed PR: none — low value relative to churn (five-file rename for a cosmetic collision); note for the backlog coordinator to decide if it is worth bundling into `selftests-split-auth`'s sibling files or skipping.

## Proposed PRs

| slug | theme | files | estimated changed lines | depends on |
|---|---|---|---|---|
| selftests-split-plugin | split `TestPluginIntegration` into 4 subject files | selftests/test_plugin.py, selftests/plugin/test_marker_deselection.py, selftests/plugin/test_terminal_output.py, selftests/plugin/test_json_report.py, selftests/plugin/test_skip_attestation.py, selftests/conftest.py | ~1100 (pure move) | none |
| selftests-split-auth | split test_auth.py by function-under-test | selftests/test_auth.py, selftests/test_auth_headless.py, selftests/test_auth_interactive.py, selftests/test_auth_scheme.py, selftests/test_auth_cache.py, selftests/test_auth_apikey.py | ~3464 (pure move) | none |
| selftests-dedupe-fixtures | consolidate TLS, Workbench-mock, and PM `_repo` helpers into conftest.py | selftests/conftest.py, selftests/test_clients_tls.py, selftests/test_auth_tls_e2e.py, selftests/test_workbench_cleanup.py, selftests/test_workbench_jupyter_cleanup.py, selftests/test_pm_ui_target.py, selftests/test_pm_repo_selection.py | ~120 | none |

Two file splits proposed under Q1 (`test_proxy.py`, `test_workbench_exec.py`, `test_cli_verify.py`, `test_workbench_cleanup.py`, `test_reporting.py`, `test_config.py`) are documented below as candidates but not written up as full PR entries, since their natural seams are already comment-delimited or class-delimited and the split is mechanical enough for the coordinator to schedule without a separate finding per file:

- `test_proxy.py` (1682 lines): comment banners already mark seven subjects (`build_proxy_map`, `proxy_for_url`, `build_mounts`, `redact_proxy_url` + `proxy_env_for_subprocess` + `verify_with_env_ca`, `playwright_proxy` — this one alone spans lines 612-1228, ~600 lines — `_launch_chromium`, browser/API parity, end-to-end). Split at minimum: `test_proxy_map.py` (build_proxy_map/proxy_for_url/build_mounts), `test_proxy_redact.py` (redact/env-for-subprocess/verify_with_env_ca), `test_proxy_playwright.py` (playwright_proxy/_launch_chromium/parity/e2e — still ~1000 lines, worth a second split into `test_proxy_playwright.py` and `test_proxy_playwright_e2e.py`).
- `test_workbench_exec.py` (1354 lines, 18 classes): natural split by IDE-exec concern — expression wrapping (`TestWrapRExpr`, `TestWrapPythonExpr*`, `TestMakeSentinels`, `TestExtractBetweenMarkers`, `TestStripRIndex`, `TestParseDoneMarker`, `TestReadFileRExpr`, lines 51-436), IDE detection/routing (`TestDetectIde`, `TestFileExistsRouting`, `TestReadFileRouting`, lines 436-846), Positron console state (`TestEnsurePositronConsole`, `TestPositronConsoleStateLabel`, `TestPositronWedgedStateDetail`, `TestVisibleTerminalInput`, lines 562-936), and terminal/bundle execution (`TestTerminalRun`, `TestB64WriteCmd`, `TestWriteBundle`, lines 936-1354).
- `test_cli_verify.py` (1562 lines, 23 classes): split by flag family — path/config resolution (`TestVerifyLocal{Test,Skip,Credential,Config}*`, `TestVerifyLocalMissingConfig`), auth flags (`TestHeadlessAuth`, `TestAuthCliFlags`, `TestProviderCliFlag`, `TestVerifyLocalSnowflakeApiAuthGuard`), TLS/proxy flags (`TestVerifyLocalTLSFlags`, `TestVerifyProxyFlagWithConfig`), and category/xdist/format flags (`TestNormalizeCategories`, `TestConfigHygieneOptIn`, `TestPerformanceOptIn`, `TestBasicFlag`, `TestVerifyDefaultXdist`, `TestFormatFlag`, `TestAllowUnprovenFlag`).
- `test_workbench_cleanup.py` (1061 lines, function-based, no classes): file is already single-subject (session cleanup); if it needs a split, do it by function under test (`is_vip_session` predicate tests vs. `quit_vip_sessions` retry/fallback tests) rather than by line count alone — did not find a natural seam over ~500 lines without reading the full file, so no finding filed.
- `test_reporting.py` (999 lines, 5 classes: `TestTestResult`, `TestReportData`, `TestProvenance`, `TestLoadResults`, `TestLoadTroubleshooting`) and `test_config.py` (887 lines, 5 classes: `TestAuthConfig`, `TestProductConfig`, `TestConnectConfig`, `TestWorkbenchConfig`, `TestWorkbenchExtensionsConfig`): both are already well under 500 lines per class on average; a split by class would work but the current single file is still navigable by class name, so no finding filed — leave to the coordinator's discretion if the >800-line threshold alone is the bar.

## Not findings

- `test_report_content.py`'s badge-color assertions (line 108, `test_primary_badge_color_matches_stylesheet`) compare `Badge.color` against `report/styles.css`, an independent source — this is the deliberate drift guard AGENTS.md documents, not a self-comparison.
- `test_scaffold_agents_md.py` parses `examples/_shared/AGENTS.md` and cross-checks it against `ast.parse`d `src/vip/fixtures.py` / `src/vip/plugin.py` source — independent sources, deliberate per AGENTS.md.
- `test_cli_report.py:118`'s `test_pyproject_force_include_matches_template_list` compares `_REPORT_TEMPLATE_FILES` against `pyproject.toml`'s force-include block — independent sources, deliberate; see the related finding above about its three sibling tests that reuse the same constant for setup, which is lower severity.
- `pytester` usage is well-scoped: `test_plugin.py` uses in-process `pytester.runpytest()` 66 times and `runpytest_subprocess` only 8 times (for cases needing true process isolation); `test_extension_fixtures.py` uses `runpytest_subprocess` exclusively (5 uses) because it specifically tests directory-ancestry fixture scoping across `--vip-extensions`, which cannot be observed in-process; `test_workbench_parallel.py` uses `runpytest_inprocess` to exercise real pytest hook execution rather than fake items. None of the sampled heavy users reach for subprocess isolation where a direct call would do.
- Mocking depth in `test_auth.py`: sampled `TestAuthenticateWorkbench` (10 tests) and `TestStartHeadlessAuthValidation` (4 tests) — all mock only the Playwright `Page`/`sync_playwright` boundary (an external dependency), while the logic under test (`_authenticate_workbench`, `start_headless_auth`) is real code that produces distinguishable results (`None` vs. specific reason strings, raised `AuthConfigError` vs. not) that a stub returning early would fail. None of the sampled 14 tests would pass if the function under test did nothing.
- Slow tests: the full suite runs in 15.86s; the 12 tests over 2s are all `pytester`-based (subprocess or in-process pytest sub-invocations in `test_extension_fixtures.py`, `test_plugin.py::TestXdistCompatibility`, `test_workbench_ordering.py`, `test_load_engine.py`) and their cost is inherent to exercising real pytest collection/execution, not a design smell.
- `tmp_toml`, `sample_results_json`, `_restore_auth_entrypoints`, and `_no_ambient_proxy` initially looked duplicated by a naive grep count, but all four are defined exactly once, in `selftests/conftest.py` — the double-count was a grep artifact from `-A1` windows overlapping consecutive decorator lines, not real duplication.
