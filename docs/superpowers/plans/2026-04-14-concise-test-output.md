# Concise Test Failure Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace verbose pytest tracebacks with concise, actionable one-liner error messages for VIP test failures.

**Architecture:** Add error classification and formatting to the existing VIP pytest plugin (`plugin.py`). A new `pytest_runtest_logreport` hook rewrites `report.longrepr` for terminal display while the existing `pytest_runtest_makereport` hook preserves full details for JSON. The JSON report carries both `concise_error` and `longrepr`; the HTML report shows the concise error prominently with full traceback expandable.

**Tech Stack:** pytest hooks, Python dataclasses, Quarto HTML templates

**Spec:** `docs/superpowers/specs/2026-04-14-concise-test-output-design.md`

---

### Task 1: Add `_format_concise_error` helper to plugin

**Files:**
- Modify: `src/vip/plugin.py:335-364`
- Test: `selftests/test_plugin.py`

- [ ] **Step 1: Write failing tests for the formatting function**

Add to `selftests/test_plugin.py`:

```python
from vip.plugin import _format_concise_error


class TestFormatConciseError:
    def test_assertion_with_message(self):
        result = _format_concise_error(
            nodeid="tests/prerequisites/test_auth.py::test_credentials_provided",
            exc_type="AssertionError",
            exc_message="VIP_TEST_USERNAME is not set. Set it in vip.toml or as an environment variable.",
        )
        assert result == (
            "test_credentials_provided: VIP_TEST_USERNAME is not set."
            " Set it in vip.toml or as an environment variable."
        )

    def test_assertion_without_message(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_auth.py::test_login",
            exc_type="AssertionError",
            exc_message="assert 403 == 200",
        )
        assert result == "test_login: AssertionError: assert 403 == 200"

    def test_unexpected_error(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_deploy.py::test_deploy_app",
            exc_type="ConnectionError",
            exc_message="Connection refused",
        )
        assert result == (
            "test_deploy_app: an unexpected error occurred: ConnectionError: Connection refused"
        )

    def test_unexpected_error_with_dotted_type(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_api.py::test_api_call",
            exc_type="httpx.ConnectError",
            exc_message="[Errno 61] Connection refused",
        )
        assert result == (
            "test_api_call: an unexpected error occurred:"
            " httpx.ConnectError: [Errno 61] Connection refused"
        )

    def test_parametrized_test_name(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_packages.py::test_package_available[numpy]",
            exc_type="AssertionError",
            exc_message="Package numpy not found",
        )
        assert result == "test_package_available[numpy]: Package numpy not found"

    def test_empty_message_falls_back(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_auth.py::test_login",
            exc_type="AssertionError",
            exc_message="",
        )
        assert result == "test_login: AssertionError"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_plugin.py::TestFormatConciseError -v`
Expected: FAIL — `_format_concise_error` cannot be imported

- [ ] **Step 3: Implement `_format_concise_error`**

Add to `src/vip/plugin.py` before the `pytest_runtest_makereport` hook (around line 333):

```python
def _format_concise_error(
    nodeid: str,
    exc_type: str,
    exc_message: str,
) -> str:
    """Format a concise one-liner error message for terminal and report display.

    AssertionError is treated as an expected test failure — the message is shown
    directly. All other exception types are prefixed with "an unexpected error
    occurred" to signal infrastructure or code issues.
    """
    test_name = nodeid.split("::")[-1] if "::" in nodeid else nodeid

    is_assertion = exc_type == "AssertionError" or exc_type.endswith(".AssertionError")

    if not exc_message:
        return f"{test_name}: {exc_type}"

    if is_assertion:
        # Custom assertion messages are user-actionable — show them directly.
        # Bare assertions (e.g. "assert 403 == 200") still need the type prefix.
        if exc_message.startswith("assert "):
            return f"{test_name}: AssertionError: {exc_message}"
        return f"{test_name}: {exc_message}"

    return f"{test_name}: an unexpected error occurred: {exc_type}: {exc_message}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/test_plugin.py::TestFormatConciseError -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/vip/plugin.py selftests/test_plugin.py
git commit -m "feat(plugin): add _format_concise_error helper for one-liner failure messages"
```

---

### Task 2: Add `_extract_exception_info` to parse `longrepr`

**Files:**
- Modify: `src/vip/plugin.py`
- Test: `selftests/test_plugin.py`

- [ ] **Step 1: Write failing tests for exception extraction**

Add to `selftests/test_plugin.py`:

```python
from vip.plugin import _extract_exception_info


class TestExtractExceptionInfo:
    def test_from_reprcrash_string(self):
        """Parse a longrepr string that looks like pytest's crash repr."""
        longrepr = (
            "src/vip_tests/prerequisites/test_auth.py:15: in test_credentials\n"
            "E   AssertionError: VIP_TEST_USERNAME is not set."
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "VIP_TEST_USERNAME is not set."

    def test_from_simple_string(self):
        longrepr = "AssertionError: HTTP not redirected"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "HTTP not redirected"

    def test_dotted_exception_type(self):
        longrepr = (
            "tests/connect/test_api.py:42: in test_call\n"
            "E   httpx.ConnectError: [Errno 61] Connection refused"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "httpx.ConnectError"
        assert exc_message == "[Errno 61] Connection refused"

    def test_bare_assertion(self):
        longrepr = (
            "tests/connect/test_auth.py:10: in test_login\n"
            "E   AssertionError: assert 403 == 200"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "assert 403 == 200"

    def test_unknown_format_falls_back(self):
        longrepr = "something weird happened"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "UnknownError"
        assert exc_message == "something weird happened"

    def test_multiline_message(self):
        longrepr = (
            "tests/test_foo.py:5: in test_it\n"
            "E   ValueError: line one\n"
            "E   line two"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "ValueError"
        assert exc_message == "line one"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_plugin.py::TestExtractExceptionInfo -v`
Expected: FAIL — `_extract_exception_info` cannot be imported

- [ ] **Step 3: Implement `_extract_exception_info`**

Add to `src/vip/plugin.py` just above `_format_concise_error`:

```python
def _extract_exception_info(longrepr: str) -> tuple[str, str]:
    """Extract (exception_type, message) from a longrepr string.

    Handles two common formats:
    - pytest's ``E   ExcType: message`` lines in tracebacks
    - plain ``ExcType: message`` strings (e.g. from failures.json)

    Returns ``("UnknownError", <full string>)`` if parsing fails.
    """
    # Look for pytest's "E   ExcType: message" line format.
    m = re.search(r"^E\s+([\w.]+(?:Error|Exception|Timeout|Refused)?):\s*(.+)", longrepr, re.MULTILINE)
    if m:
        return m.group(1), m.group(2).strip()

    # Fall back to "ExcType: message" at the start of the string.
    m = re.match(r"([\w.]+(?:Error|Exception|Timeout|Refused)?):\s*(.+)", longrepr.strip())
    if m:
        return m.group(1), m.group(2).strip()

    return "UnknownError", longrepr.strip()[:200]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/test_plugin.py::TestExtractExceptionInfo -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/vip/plugin.py selftests/test_plugin.py
git commit -m "feat(plugin): add _extract_exception_info to parse longrepr strings"
```

---

### Task 3: Store `concise_error` in JSON results

**Files:**
- Modify: `src/vip/plugin.py:335-364` (the `pytest_runtest_makereport` hookwrapper)
- Modify: `src/vip/plugin.py:412-434` (the `pytest_sessionfinish` failures.json section)
- Test: `selftests/test_plugin.py`

- [ ] **Step 1: Write failing test for concise_error in JSON**

Add to `TestPluginIntegration` in `selftests/test_plugin.py`:

```python
def test_json_report_includes_concise_error(self, selftest_pytester):
    selftest_pytester.makepyfile(
        """
        def test_expected_failure():
            assert False, "Something went wrong"

        def test_unexpected_failure():
            raise ValueError("bad value")
        """
    )
    report_path = selftest_pytester.path / "results.json"
    result = selftest_pytester.runpytest(
        "--vip-config=vip.toml",
        f"--vip-report={report_path}",
    )
    result.assert_outcomes(failed=2)

    data = json.loads(report_path.read_text())
    failed = [r for r in data["results"] if r["outcome"] == "failed"]
    assert len(failed) == 2

    expected = next(r for r in failed if "expected_failure" in r["nodeid"])
    assert expected["concise_error"] is not None
    assert "Something went wrong" in expected["concise_error"]
    assert expected["longrepr"] is not None  # full traceback preserved

    unexpected = next(r for r in failed if "unexpected_failure" in r["nodeid"])
    assert "an unexpected error occurred" in unexpected["concise_error"]
    assert "ValueError" in unexpected["concise_error"]
```

- [ ] **Step 2: Write failing test for concise_error in failures.json**

Add to `TestPluginIntegration` in `selftests/test_plugin.py`:

```python
def test_failures_json_uses_concise_error(self, selftest_pytester):
    selftest_pytester.makepyfile(
        """
        def test_will_fail():
            assert False, "Config is missing"
        """
    )
    report_path = selftest_pytester.path / "results.json"
    selftest_pytester.runpytest(
        "--vip-config=vip.toml",
        f"--vip-report={report_path}",
    )
    failures_path = selftest_pytester.path / "failures.json"
    assert failures_path.exists()

    data = json.loads(failures_path.read_text())
    assert len(data["failures"]) == 1
    assert "Config is missing" in data["failures"][0]["error_summary"]
    # Should be the concise format, not a 500-char truncation
    assert len(data["failures"][0]["error_summary"]) < 200
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest selftests/test_plugin.py::TestPluginIntegration::test_json_report_includes_concise_error selftests/test_plugin.py::TestPluginIntegration::test_failures_json_uses_concise_error -v`
Expected: FAIL — `concise_error` key not in JSON

- [ ] **Step 4: Modify `pytest_runtest_makereport` to compute and store concise_error**

In `src/vip/plugin.py`, modify the `pytest_runtest_makereport` hook (around line 335). Change the `results.append(...)` block to also compute and include `concise_error`:

```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):  # noqa: ARG001
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and report.skipped):
        if _active_config is None:
            return
        results = _active_config.stash.get(_results_key, None)
        if results is None:
            return
        markers: list[str] = []
        scenario_meta: dict[str, str | None] = {}
        try:
            markers = [m.name for m in item.iter_markers()]
        except Exception:
            pass
        item_stash = getattr(item, "stash", None)
        if item_stash is not None:
            scenario_meta = item_stash.get(_scenario_stash_key, {})

        longrepr_str = str(report.longrepr) if report.longrepr else None
        concise_error = None
        if report.outcome == "failed" and longrepr_str:
            exc_type, exc_message = _extract_exception_info(longrepr_str)
            concise_error = _format_concise_error(report.nodeid, exc_type, exc_message)

        results.append(
            {
                "nodeid": report.nodeid,
                "outcome": report.outcome,
                "duration": report.duration,
                "longrepr": longrepr_str,
                "concise_error": concise_error,
                "markers": markers,
                "scenario_title": scenario_meta.get("scenario_title"),
                "feature_description": scenario_meta.get("feature_description"),
            }
        )
```

- [ ] **Step 5: Modify `pytest_sessionfinish` to use concise_error in failures.json**

In `src/vip/plugin.py`, in the `pytest_sessionfinish` function (around line 418), change the `failures_payload` construction:

Replace:

```python
        failures_payload = {
            "deployment": cfg.deployment_name,
            "generated_at": payload["generated_at"],
            "failures": [
                {
                    "test": r["nodeid"],
                    "scenario": r.get("scenario_title"),
                    "feature": r.get("feature_description"),
                    "error_summary": (r.get("longrepr") or "")[:500],
                }
                for r in failures
            ],
        }
```

With:

```python
        failures_payload = {
            "deployment": cfg.deployment_name,
            "generated_at": payload["generated_at"],
            "failures": [
                {
                    "test": r["nodeid"],
                    "scenario": r.get("scenario_title"),
                    "feature": r.get("feature_description"),
                    "error_summary": r.get("concise_error") or (r.get("longrepr") or "")[:500],
                }
                for r in failures
            ],
        }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest selftests/test_plugin.py::TestPluginIntegration::test_json_report_includes_concise_error selftests/test_plugin.py::TestPluginIntegration::test_failures_json_uses_concise_error -v`
Expected: Both PASS

- [ ] **Step 7: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add src/vip/plugin.py selftests/test_plugin.py
git commit -m "feat(plugin): store concise_error in JSON results and failures.json"
```

---

### Task 4: Add `--vip-verbose` option and `pytest_runtest_logreport` hook

**Files:**
- Modify: `src/vip/plugin.py:57-81` (pytest_addoption)
- Modify: `src/vip/plugin.py` (new hook)
- Test: `selftests/test_plugin.py`

- [ ] **Step 1: Write failing test for concise terminal output**

Add to `TestPluginIntegration` in `selftests/test_plugin.py`:

```python
def test_concise_failure_output(self, selftest_pytester):
    """Failed test shows one-liner, not full traceback."""
    selftest_pytester.makepyfile(
        """
        def test_with_message():
            assert False, "Username is missing"
        """
    )
    result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
    result.assert_outcomes(failed=1)
    # The concise message should appear in output.
    result.stdout.fnmatch_lines(["*Username is missing*"])
    # The full traceback "E   AssertionError" should NOT appear.
    result.stdout.no_fnmatch_line("*E   AssertionError*")

def test_unexpected_error_output(self, selftest_pytester):
    """Non-assertion errors show 'an unexpected error occurred' prefix."""
    selftest_pytester.makepyfile(
        """
        def test_crashes():
            raise ValueError("bad value")
        """
    )
    result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*an unexpected error occurred*ValueError*bad value*"])
```

- [ ] **Step 2: Write failing test for `--vip-verbose` restoring tracebacks**

Add to `TestPluginIntegration` in `selftests/test_plugin.py`:

```python
def test_vip_verbose_shows_full_traceback(self, selftest_pytester):
    """--vip-verbose restores pytest's default traceback output."""
    selftest_pytester.makepyfile(
        """
        def test_with_message():
            assert False, "Username is missing"
        """
    )
    result = selftest_pytester.runpytest("--vip-config=vip.toml", "--vip-verbose", "-v")
    result.assert_outcomes(failed=1)
    # Full traceback should appear — look for pytest's "E" prefix lines.
    result.stdout.fnmatch_lines(["*E   AssertionError*"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest selftests/test_plugin.py::TestPluginIntegration::test_concise_failure_output selftests/test_plugin.py::TestPluginIntegration::test_unexpected_error_output selftests/test_plugin.py::TestPluginIntegration::test_vip_verbose_shows_full_traceback -v`
Expected: FAIL — `--vip-verbose` not recognized; output still has full tracebacks

- [ ] **Step 4: Add `--vip-verbose` option**

In `src/vip/plugin.py`, add to the `pytest_addoption` function (after the `--interactive-auth` option, around line 81):

```python
    group.addoption(
        "--vip-verbose",
        action="store_true",
        default=False,
        help="Show full pytest tracebacks instead of concise error messages.",
    )
```

- [ ] **Step 5: Add `pytest_runtest_logreport` hook**

Add to `src/vip/plugin.py` after the `pytest_runtest_makereport` hook:

```python
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Replace verbose tracebacks with concise error messages for terminal display.

    Runs after pytest_runtest_makereport has captured the full longrepr for
    JSON reporting. This modifies report.longrepr in-place so the terminal
    reporter shows the concise format.
    """
    if _active_config is None:
        return
    if _active_config.getoption("--vip-verbose", default=False):
        return
    if report.outcome not in ("failed", "error"):
        return
    if not report.longrepr:
        return

    longrepr_str = str(report.longrepr)
    exc_type, exc_message = _extract_exception_info(longrepr_str)
    report.longrepr = _format_concise_error(report.nodeid, exc_type, exc_message)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest selftests/test_plugin.py::TestPluginIntegration::test_concise_failure_output selftests/test_plugin.py::TestPluginIntegration::test_unexpected_error_output selftests/test_plugin.py::TestPluginIntegration::test_vip_verbose_shows_full_traceback -v`
Expected: All 3 PASS

- [ ] **Step 7: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add src/vip/plugin.py selftests/test_plugin.py
git commit -m "feat(plugin): add --vip-verbose option and concise terminal output hook"
```

---

### Task 5: Add `--verbose` flag to `vip verify` CLI

**Files:**
- Modify: `src/vip/cli.py:280` (command assembly in `_run_verify_local`)
- Modify: `src/vip/cli.py:561-677` (verify subparser arguments)
- Test: `selftests/test_cli_verify.py`

- [ ] **Step 1: Write failing test for `--verbose` flag passthrough**

Add to `selftests/test_cli_verify.py`:

```python
class TestVerifyLocalVerboseFlag:
    """vip verify --verbose should pass --vip-verbose to pytest."""

    def test_verbose_flag_passes_vip_verbose(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), verbose=True))
        assert "--vip-verbose" in cmd

    def test_no_verbose_flag_omits_vip_verbose(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), verbose=False))
        assert "--vip-verbose" not in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_cli_verify.py::TestVerifyLocalVerboseFlag -v`
Expected: FAIL — `verbose` not a valid key for `_make_args`

- [ ] **Step 3: Update `_make_args` helper to include `verbose` default**

In `selftests/test_cli_verify.py`, add `"verbose": False,` to the `defaults` dict in `_make_args` (around line 24):

```python
def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace for _run_verify_local."""
    defaults = {
        "config": None,
        "connect_url": None,
        "workbench_url": None,
        "package_manager_url": None,
        "report": "report/results.json",
        "interactive_auth": False,
        "extensions": [],
        "categories": None,
        "filter_expr": None,
        "pytest_args": [],
        "verbose": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
```

- [ ] **Step 4: Add `--verbose` argument to verify subparser**

In `src/vip/cli.py`, add after the `--report` argument (around line 624):

```python
    verify_parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show full pytest tracebacks instead of concise error messages",
    )
```

- [ ] **Step 5: Pass `--vip-verbose` when `--verbose` is set**

In `src/vip/cli.py`, in `_run_verify_local` (around line 304, before `cmd.extend(args.pytest_args)`), add:

```python
    if args.verbose:
        cmd.append("--vip-verbose")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest selftests/test_cli_verify.py::TestVerifyLocalVerboseFlag -v`
Expected: Both PASS

- [ ] **Step 7: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add src/vip/cli.py selftests/test_cli_verify.py
git commit -m "feat(cli): add --verbose flag to vip verify for full tracebacks"
```

---

### Task 6: Remove hardcoded `--tb=short` from K8s job

**Files:**
- Modify: `src/vip/verify/job.py:73`
- Test: `selftests/test_job.py`

- [ ] **Step 1: Read the existing job test file**

Read `selftests/test_job.py` to understand what's already tested and how.

- [ ] **Step 2: Write failing test**

Add to `selftests/test_job.py` (following the existing test patterns):

```python
def test_pytest_args_no_tb_flag():
    """The K8s job should not hardcode --tb=short; the plugin controls traceback format."""
    from vip.verify.job import create_job
    # We can't run create_job without kubectl, but we can inspect the source
    # to verify --tb=short is not present.
    import inspect
    source = inspect.getsource(create_job)
    assert "--tb=short" not in source
```

Note: If the existing tests already capture the pytest args constructed by `create_job`, use that pattern instead. Read the file first to determine the right approach.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest selftests/test_job.py::test_pytest_args_no_tb_flag -v`
Expected: FAIL — `--tb=short` is still in the source

- [ ] **Step 4: Remove `--tb=short` from job.py**

In `src/vip/verify/job.py` line 73, change:

```python
    pytest_args = ["pytest", "--vip-config=/config/vip.toml", "-v", "--tb=short"]
```

To:

```python
    pytest_args = ["pytest", "--vip-config=/config/vip.toml", "-v"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest selftests/test_job.py::test_pytest_args_no_tb_flag -v`
Expected: PASS

- [ ] **Step 6: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/vip/verify/job.py selftests/test_job.py
git commit -m "fix(job): remove hardcoded --tb=short from K8s pytest command"
```

---

### Task 7: Add `concise_error` to reporting module

**Files:**
- Modify: `src/vip/reporting.py:17-25` (TestResult dataclass)
- Modify: `src/vip/reporting.py:94-132` (load_results function)
- Test: `selftests/test_reporting.py`

- [ ] **Step 1: Write failing test for `concise_error` field**

Add to `selftests/test_reporting.py`:

```python
class TestConciseError:
    def test_concise_error_field_default_none(self):
        r = TestResult(nodeid="a", outcome="passed")
        assert r.concise_error is None

    def test_concise_error_loaded_from_json(self, tmp_path):
        import json

        data = {
            "deployment_name": "Test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "exit_status": 1,
            "products": {},
            "results": [
                {
                    "nodeid": "tests/connect/test_auth.py::test_login",
                    "outcome": "failed",
                    "duration": 1.0,
                    "longrepr": "full traceback here...",
                    "concise_error": "test_login: Login failed",
                    "markers": ["connect"],
                },
                {
                    "nodeid": "tests/connect/test_api.py::test_api",
                    "outcome": "passed",
                    "duration": 0.5,
                    "markers": [],
                },
            ],
        }
        p = tmp_path / "results.json"
        p.write_text(json.dumps(data))
        rd = load_results(p)
        assert rd.results[0].concise_error == "test_login: Login failed"
        assert rd.results[1].concise_error is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_reporting.py::TestConciseError -v`
Expected: FAIL — `concise_error` not an attribute of `TestResult`

- [ ] **Step 3: Add `concise_error` field to TestResult**

In `src/vip/reporting.py`, add to the `TestResult` dataclass (after `longrepr`, around line 22):

```python
    concise_error: str | None = None
```

- [ ] **Step 4: Read `concise_error` in `load_results`**

In `src/vip/reporting.py`, in the `load_results` function, add `concise_error` to the `TestResult` constructor (around line 107):

Change:

```python
    results = [
        TestResult(
            nodeid=r["nodeid"],
            outcome=r["outcome"],
            duration=r.get("duration", 0.0),
            longrepr=r.get("longrepr"),
            markers=r.get("markers", []),
            scenario_title=r.get("scenario_title"),
            feature_description=r.get("feature_description"),
        )
        for r in raw.get("results", [])
    ]
```

To:

```python
    results = [
        TestResult(
            nodeid=r["nodeid"],
            outcome=r["outcome"],
            duration=r.get("duration", 0.0),
            longrepr=r.get("longrepr"),
            concise_error=r.get("concise_error"),
            markers=r.get("markers", []),
            scenario_title=r.get("scenario_title"),
            feature_description=r.get("feature_description"),
        )
        for r in raw.get("results", [])
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest selftests/test_reporting.py::TestConciseError -v`
Expected: Both PASS

- [ ] **Step 6: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/vip/reporting.py selftests/test_reporting.py
git commit -m "feat(reporting): add concise_error field to TestResult dataclass"
```

---

### Task 8: Update HTML report to show concise errors prominently

**Files:**
- Modify: `report/details.qmd:307-319`

- [ ] **Step 1: Modify the error display section**

In `report/details.qmd`, find the error traceback section (around line 307):

Replace:

```python
            # Error traceback for failed tests
            error_html = ""
            if item.outcome == "failed" and item.longrepr:
                error_id = f"vip-detail-error-{_error_idx}"
                _error_idx += 1
                error_html = (
                    f'<details class="vip-fail-details">'
                    f"<summary>Error traceback</summary>"
                    f'<div class="vip-fail-error-wrap">'
                    f'<button class="vip-copy-btn" data-target="{error_id}"'
                    f' title="Copy to clipboard">Copy</button>'
                    f'<pre id="{error_id}" class="vip-fail-error">'
                    f"{_esc(item.longrepr)}</pre>"
                    f"</div></details>"
                )
```

With:

```python
            # Error display for failed tests: concise message + expandable traceback
            error_html = ""
            if item.outcome == "failed":
                parts = []
                # Concise error — always visible
                concise = getattr(item, "concise_error", None) or ""
                if concise:
                    parts.append(
                        f'<div class="vip-fail-concise" style="'
                        f"font-size:0.875rem;color:#dc2626;font-weight:600;"
                        f'margin-top:0.375rem">{_esc(concise)}</div>'
                    )
                # Full traceback — expandable
                if item.longrepr:
                    error_id = f"vip-detail-error-{_error_idx}"
                    _error_idx += 1
                    parts.append(
                        f'<details class="vip-fail-details">'
                        f"<summary>Full error traceback</summary>"
                        f'<div class="vip-fail-error-wrap">'
                        f'<button class="vip-copy-btn" data-target="{error_id}"'
                        f' title="Copy to clipboard">Copy</button>'
                        f'<pre id="{error_id}" class="vip-fail-error">'
                        f"{_esc(item.longrepr)}</pre>"
                        f"</div></details>"
                    )
                error_html = "".join(parts)
```

- [ ] **Step 2: Verify the report renders**

Run: `uv run pytest selftests/ -v` (no report tests break)
Run: `just check`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add report/details.qmd
git commit -m "feat(report): show concise error prominently with expandable traceback"
```

---

### Task 9: Update `sample_results_json` fixture and verify existing tests

**Files:**
- Modify: `selftests/conftest.py:31-99`
- Test: `selftests/test_reporting.py`

- [ ] **Step 1: Update the sample fixture to include `concise_error`**

In `selftests/conftest.py`, update the failed test entry in `sample_results_json` (around line 90):

Change:

```python
            {
                "nodeid": "tests/security/test_https.py::test_connect_https",
                "outcome": "failed",
                "duration": 0.8,
                "longrepr": "AssertionError: HTTP not redirected",
                "markers": ["security"],
            },
```

To:

```python
            {
                "nodeid": "tests/security/test_https.py::test_connect_https",
                "outcome": "failed",
                "duration": 0.8,
                "longrepr": "AssertionError: HTTP not redirected",
                "concise_error": "test_connect_https: HTTP not redirected",
                "markers": ["security"],
            },
```

- [ ] **Step 2: Run full selftests to verify nothing breaks**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add selftests/conftest.py
git commit -m "test: add concise_error to sample_results_json fixture"
```

---

### Task 10: End-to-end integration test

**Files:**
- Test: `selftests/test_plugin.py`

- [ ] **Step 1: Write end-to-end test covering full flow**

Add to `TestPluginIntegration` in `selftests/test_plugin.py`:

```python
def test_concise_output_end_to_end(self, selftest_pytester):
    """Full flow: concise terminal output + JSON report with both fields."""
    selftest_pytester.makepyfile(
        """
        def test_passes():
            assert True

        def test_assertion_fails():
            assert False, "Deployment check failed"

        def test_error_fails():
            raise RuntimeError("connection lost")
        """
    )
    report_path = selftest_pytester.path / "results.json"
    result = selftest_pytester.runpytest(
        "--vip-config=vip.toml",
        f"--vip-report={report_path}",
        "-v",
    )
    result.assert_outcomes(passed=1, failed=2)

    # Terminal: concise output
    result.stdout.fnmatch_lines(["*Deployment check failed*"])
    result.stdout.fnmatch_lines(["*an unexpected error occurred*RuntimeError*connection lost*"])

    # JSON: both fields present
    data = json.loads(report_path.read_text())
    failed = [r for r in data["results"] if r["outcome"] == "failed"]
    for r in failed:
        assert r["concise_error"] is not None
        assert r["longrepr"] is not None
        assert len(r["longrepr"]) > len(r["concise_error"])

    passed = [r for r in data["results"] if r["outcome"] == "passed"]
    for r in passed:
        assert r["concise_error"] is None
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest selftests/test_plugin.py::TestPluginIntegration::test_concise_output_end_to_end -v`
Expected: PASS

- [ ] **Step 3: Run full selftests and lint**

Run: `uv run pytest selftests/ -v`
Run: `just check`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add selftests/test_plugin.py
git commit -m "test(plugin): add end-to-end integration test for concise output"
```
