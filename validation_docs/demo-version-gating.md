# Feature: robust version gating (#410)

*2026-07-01T22:55:10Z by Showboat 0.6.1*
<!-- showboat-id: 8caba893-f614-4413-a0a3-d9ba1b4e8842 -->

Issue #410 replaces the old naive `_version_tuple` marker gate with a real Posit calendar-version parser (`vip.version.ProductVersion`), adds an explicit unknown-version policy (skip + N/A + warn instead of an optimistic pass), a distinct 'N/A (version)' report status, and versioned page-object classes for UI selectors/behavior that change across Workbench releases.

## 1. `ProductVersion` parses and compares Posit calendar versions

Handles `YYYY.MM.patch` plus `-dev`/`-daily`/`-preview` pre-release suffixes and `+build` metadata, with pre-releases sorting before the final release of the same numeric version.

```bash
uv run python -c "
from vip.version import ProductVersion as V

print('2026.06.0-dev+123      <', '2026.06.0-daily.20260615 :', V('2026.06.0-dev+123') < V('2026.06.0-daily.20260615'))
print('2026.06.0-preview      <', '2026.06.0                :', V('2026.06.0-preview') < V('2026.06.0'))
print('2026.05.9              <', '2026.06.0                :', V('2026.05.9') < V('2026.06.0'))
print('2026.06.0+build1      ==', '2026.06.0+build2         :', V('2026.06.0+build1') == V('2026.06.0+build2'))

try:
    V('not-a-version')
except ValueError as exc:
    print('unparseable input raises ValueError:', exc)
"
```

```output
2026.06.0-dev+123      < 2026.06.0-daily.20260615 : True
2026.06.0-preview      < 2026.06.0                : True
2026.05.9              < 2026.06.0                : True
2026.06.0+build1      == 2026.06.0+build2         : True
unparseable input raises ValueError: Cannot parse 'not-a-version' as a Posit calendar version (expected YYYY.MM.patch[-dev|-daily|-preview][+build])
```

## 2. Unknown version now skips + warns instead of running optimistically

Previously, `pc.version is None` meant a `min_version`-marked test ran optimistically (silent spurious-pass risk). Now it skips, is flagged N/A for the report, and emits a warning naming the gap.

```bash
uv run pytest selftests/test_plugin.py -k 'version_skip' -v 2>&1 | grep -E 'PASSED|FAILED' | sed -E 's/\[[[:space:]]*[0-9]+%\]//' | sort
uv run pytest selftests/test_plugin.py -k 'version_skip' -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
selftests/test_plugin.py::TestPluginIntegration::test_version_skip PASSED 
selftests/test_plugin.py::TestPluginIntegration::test_version_skip_known_below_minimum_is_plain_skip PASSED 
selftests/test_plugin.py::TestPluginIntegration::test_version_skip_unparseable_deployed_version PASSED 
3 passed
```

## 3. Versioned page objects: cumulative inheritance + a `get_<page>(version)` factory

`Homepage_2026_05` overrides only the one selector that changed (the shadcn dialog container). A separate version-threshold strategy dict handles the New Session dialog's close *behavior* change (Escape vs. the legacy Cancel button), which isn't expressible as a selector override.

```bash
uv run python -c "
from vip_tests.workbench.pages import get_homepage, get_new_session_dialog_close_strategy, Homepage, Homepage_2026_05

print('get_homepage(\"2026.04.0\") ->', get_homepage('2026.04.0').__name__)
print('get_homepage(\"2026.05.0\") ->', get_homepage('2026.05.0').__name__)
print('get_homepage(\"2026.06.1\") ->', get_homepage('2026.06.1').__name__)
print('get_homepage(None)          ->', get_homepage(None).__name__)

print()
print('SESSION_DETAILS_DIALOG (pre-2026.05):', Homepage.SESSION_DETAILS_DIALOG)
print('SESSION_DETAILS_DIALOG (2026.05+)   :', Homepage_2026_05.SESSION_DETAILS_DIALOG)

print()
print('close strategy pre-2026.05 ->', get_new_session_dialog_close_strategy('2026.04.0').__name__)
print('close strategy 2026.05+    ->', get_new_session_dialog_close_strategy('2026.05.0').__name__)
"
```

```output
get_homepage("2026.04.0") -> Homepage
get_homepage("2026.05.0") -> Homepage_2026_05
get_homepage("2026.06.1") -> Homepage_2026_05
get_homepage(None)          -> Homepage

SESSION_DETAILS_DIALOG (pre-2026.05): [class*='modal-dialog']
SESSION_DETAILS_DIALOG (2026.05+)   : [data-slot='dialog-content']

close strategy pre-2026.05 -> _close_dialog_via_cancel_button
close strategy 2026.05+    -> _close_dialog_via_escape
```

## 4. Distinct 'N/A (version)' report status

`TestResult.status` returns `\"na_version\"` when a test was skipped due to an undetermined version, separate from an ordinary `\"skipped\"` (e.g. an unconfigured feature). The Quarto templates key their styling off `.status`, so version gaps get their own amber badge instead of blending into the grey 'SKIP' bucket.

```bash
uv run python -c "
from vip.reporting import TestResult

ordinary_skip = TestResult(nodeid='t::a', outcome='skipped', na_version=False)
na_skip = TestResult(nodeid='t::b', outcome='skipped', na_version=True)
passed = TestResult(nodeid='t::c', outcome='passed', na_version=True)  # na_version only matters when actually skipped

print('ordinary skip .status ->', ordinary_skip.status)
print('N/A-by-version .status ->', na_skip.status)
print('passed (na_version flag ignored) .status ->', passed.status)
"
```

```output
ordinary skip .status -> skipped
N/A-by-version .status -> na_version
passed (na_version flag ignored) .status -> passed
```

## 5. Full selftest coverage for the new module and page-object factory

```bash
uv run pytest selftests/test_version.py selftests/test_pages.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
45 passed
```

## 6. Full selftest suite + lint/format/type checks

```bash
uv run pytest selftests/ -q --ignore=selftests/test_load_engine.py 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
855 passed, 22 warnings
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
147 files already formatted
```

`mypy` type checking on `src/vip/`

```bash
uv run mypy src/vip/ 2>&1 | tail -1
```

```output
Success: no issues found in 28 source files
```
