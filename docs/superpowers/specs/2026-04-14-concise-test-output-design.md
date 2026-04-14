# Concise Test Failure Output

**Date:** 2026-04-14
**Status:** Draft

## Problem

When a VIP test fails, pytest produces a verbose traceback that includes internal
pytest/fixture code, full call stacks, and raw assertion details. This output is
unhelpful for the target audience (operators validating Posit Team deployments).
They need a clear, actionable error message — not a Python stack trace.

Example of current output for a missing credential:

```
fixturefunc = <function username_not_empty at 0x10d919590>, request = ...
kwargs = {'credentials': {'auth_provider': 'password', ...}}

    def call_fixture_func(fixturefunc, request, kwargs):
        ...
>       fixture_result = fixturefunc(**kwargs)

.venv/lib/python3.14/site-packages/_pytest/fixtures.py:915:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

>   assert credentials["username"], (
        "VIP_TEST_USERNAME is not set. Set it in vip.toml or as an environment variable."
    )
E   AssertionError: VIP_TEST_USERNAME is not set. ...
```

Desired output:

```
test_credentials_provided: VIP_TEST_USERNAME is not set. Set it in vip.toml or as an environment variable.
```

## Requirements

1. Test failures display a single concise line: `<test_name>: <error_message>`.
2. Passing and skipped tests keep their current pytest output format.
3. Error classification:
   - **Expected** (any `AssertionError`): Show `test_name: <message>`.
   - **Unexpected** (all other exception types): Show
     `test_name: an unexpected error occurred: <ExceptionType>: <message>`.
4. A `--verbose` flag on `vip verify` (mapped to `--vip-verbose` in the plugin)
   restores full pytest tracebacks on the terminal.
5. The JSON report (`results.json`) includes both a `concise_error` field and the
   full `longrepr` for every failure.
6. The `failures.json` `error_summary` field uses the concise error message.
7. The HTML report (Quarto) shows the concise error prominently on each failed test
   card, with the full traceback available in an expandable `<details>` section.

## Design

### Error classification and formatting

A new helper function `_format_concise_error` in `plugin.py` takes a
`pytest.TestReport` and returns a one-liner string.

**Inputs:**
- `report.nodeid` — extract the short function name (everything after the last `::`)
- `report.longrepr` — the full failure representation from pytest

**Classification logic:**
- Determine the exception type. The `report.longrepr` object is typically a
  `ExceptionChainRepr` or `ReprExceptionInfo`; extract the exception type name and
  message from its last `reprcrash` attribute (which has `message` and `path`).
- When `longrepr` is a plain string (e.g., from xdist workers or collection
  errors), parse the exception type and message from the string using a regex
  like `r"^(\w+(?:\.\w+)*Error): (.+)"`. If parsing fails, use the full string.
- If the exception is an `AssertionError` (including subclasses): format as
  `{test_name}: {message}`.
- If the exception is any other type: format as
  `{test_name}: an unexpected error occurred: {ExcType}: {message}`.
- If the message is empty, fall back to the string representation of `longrepr`
  truncated to a reasonable length.
- Setup failures (fixture crashes) are classified the same way as call failures.
  The `when` field distinguishes them in the report but the concise formatting
  logic is identical.

**Test name:** The short function name from `report.nodeid`. For
`src/vip_tests/prerequisites/test_auth_configured.py::test_credentials_provided`,
this is `test_credentials_provided`. For parametrized tests like
`test_foo[param1]`, the name includes the parameter suffix.

### Terminal output

**New hook: `pytest_runtest_logreport`**

This hook fires when pytest is about to display a test result. For failed reports
(where `report.when == "call"` or `report.when == "setup"` and not skipped):

1. If `--vip-verbose` is set, do nothing (pytest renders its default output).
2. Otherwise, replace `report.longrepr` with the concise one-liner string.

**Hook ordering:** `pytest_runtest_makereport` (existing, hookwrapper) runs first
and captures the full `longrepr` for JSON reporting. `pytest_runtest_logreport`
(new) runs second and modifies the report for terminal display. This ensures
the JSON gets full details while the terminal gets the concise format.

**New CLI option: `--vip-verbose`**

Added via `pytest_addoption` in the existing VIP option group. Boolean flag,
default `False`.

### CLI integration

**`vip verify` command (`cli.py`):**

Add a `--verbose` argument to the `verify` subparser. When set, append
`--vip-verbose` to the pytest command. The default (no flag) produces concise
output.

**K8s mode (`job.py`):**

Remove the hardcoded `--tb=short` from the K8s pytest command. The plugin now
controls traceback formatting consistently across local and K8s execution.

### JSON report changes

**`results.json` — written by `pytest_sessionfinish`:**

Each result dict gains a new field:

```json
{
  "nodeid": "...",
  "outcome": "failed",
  "longrepr": "<full traceback — unchanged>",
  "concise_error": "test_credentials_provided: VIP_TEST_USERNAME is not set. ...",
  ...
}
```

The `concise_error` field is `null` for passing/skipped tests.

**`failures.json`:**

The `error_summary` field changes from a 500-character truncation of `longrepr`
to the concise error message:

```json
{
  "test": "...",
  "error_summary": "test_credentials_provided: VIP_TEST_USERNAME is not set. ..."
}
```

### Reporting module changes

**`reporting.py` — `TestResult` dataclass:**

Add a `concise_error: str | None = None` field. `load_results()` reads it from
the JSON.

### HTML report changes

**`details.qmd`:**

For failed test cards, change the layout from:

- (current) Collapsed `<details>` with full traceback

To:

- (new) Concise error message displayed prominently (always visible)
- (new) Full traceback in a collapsed `<details>` element below it

The concise error is read from `item.concise_error`. The full traceback remains
in `item.longrepr` and renders inside the existing expandable section.

### Files to modify

| File | Change |
|------|--------|
| `src/vip/plugin.py` | Add `_format_concise_error`, `pytest_runtest_logreport` hook, `--vip-verbose` option, store `concise_error` in results |
| `src/vip/cli.py` | Add `--verbose` to `verify` subparser, pass `--vip-verbose` to pytest |
| `src/vip/verify/job.py` | Remove hardcoded `--tb=short` |
| `src/vip/reporting.py` | Add `concise_error` field to `TestResult`, load it in `load_results()` |
| `report/details.qmd` | Show concise error prominently, keep full traceback in expandable section |
| `selftests/` | New tests for error classification, concise formatting, verbose toggle |

### What does NOT change

- Passing and skipped test output (terminal and report)
- Test collection, deselection, and marker behavior
- The `--vip-config`, `--vip-report`, `--interactive-auth` options
- The Quarto report structure (summary page, troubleshooting hints)
- Any test files or step definitions
