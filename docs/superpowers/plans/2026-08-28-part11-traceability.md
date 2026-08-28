# Part 11 Control Tagging and Traceability Export Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Goal: Let a Gherkin scenario declare the compliance control it satisfies, harden `results.json` into an attributable evidence record, and add a `vip trace` command that joins the two into a traceability matrix.

Architecture: Three layers, built bottom-up. First `results.json` gains provenance (schema version, per-test timestamps, execution attribution, a checksum sidecar) — this ships value on its own. Then `@control-*` Gherkin tags are registered as real pytest markers so they survive strict-marker CI and reach `results.json`. Finally a new `src/vip/traceability.py` joins a customer-supplied `controls.toml` against those markers and renders CSV/JSON for a downstream PDF pipeline.

Tech Stack: Python 3.10+, pytest 9.1.1, pytest-bdd 8.1.0, pytest-xdist, argparse, tomllib, stdlib `csv`/`hashlib`/`subprocess`. No new dependencies.

Spec: `docs/superpowers/specs/2026-08-28-part11-traceability-design.md`

## Global Constraints

- Run everything through `uv run`. Never bare `python` or `pip`.
- Ruff is linter and formatter, line length 100, rules `E`, `F`, `I`, `UP`. CI pins ruff 0.15.0. Lint paths must include `examples/`: `uv run ruff check src/ src/vip_tests/ selftests/ examples/`. If `uv run ruff` is unavailable locally, use `uvx ruff@0.15.0`.
- Selftests run randomized. Never pass `-p no:randomly` — CI runs them randomized and disabling the plugin hides the order-dependent failures it exists to catch.
- Never import a pytest-bdd step module (anything under `src/vip_tests/**` calling `@scenario`/`scenarios()`) from inside a selftest. `@scenario` inspects the caller's frame at import time and raises `IndexError`. Use `pytester` subprocess runs or `--collect-only` instead.
- Every new field added to `results.json` must be optional on the dataclass and read with `.get()` in `load_results`. `ReportData`'s existing docstring (`reporting.py:114-119`) states the rule: defaults are `None` rather than a concrete-looking value so an older `results.json` loads as "not recorded" instead of silently claiming a value that was never measured.
- Never fail or warn a verification run because provenance collection failed. Every probe degrades to `None`.
- Commit after every task. Conventional-commit titles, lowercase description, no trailing period, under 70 chars.
- No `**` bold in any markdown file this plan creates or edits.

## Task ordering and shipping seams

Tasks 1-4 (evidence record) are independent of 5-11 and ship value alone. Tasks 5-6 (tagging) are independent of 1-4. Task 7 onward consumes both. If this needs to be split across people, the seam is after Task 4 and after Task 6.

---

### Task 1: `schema_version` on results.json

Establishes the additive-field pattern every later task follows.

Files:
- Modify: `src/vip/reporting.py` (add constant, `ReportData` field, `load_results` read)
- Modify: `src/vip/plugin.py:1299-1310` (payload)
- Test: `selftests/test_results_schema.py` (create)

Interfaces:
- Consumes: nothing
- Produces: `reporting.RESULTS_SCHEMA_VERSION: str` (value `"1.0"`); `ReportData.schema_version: str | None`

- [ ] Step 1: Write the failing test

Create `selftests/test_results_schema.py`:

```python
import json

from vip.reporting import RESULTS_SCHEMA_VERSION, load_results


def test_schema_version_is_loaded(tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({"schema_version": "1.0", "results": []}))
    assert load_results(p).schema_version == "1.0"


def test_pre_1_0_results_load_with_null_schema_version(tmp_path):
    """An archived results.json written before versioning must still load."""
    p = tmp_path / "results.json"
    p.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "results": [{"nodeid": "a.py::test_x", "outcome": "passed"}],
            }
        )
    )
    data = load_results(p)
    assert data.schema_version is None
    assert len(data.results) == 1


def test_current_schema_version_constant():
    assert RESULTS_SCHEMA_VERSION == "1.0"
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_results_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'RESULTS_SCHEMA_VERSION'`

- [ ] Step 3: Write minimal implementation

In `src/vip/reporting.py`, below `VALID_FORMATS`:

```python
# results.json schema version. Bump the minor for additive changes (a new
# field); bump the major for a removal, a rename, or a change in the meaning
# of an existing field. Consumers accept an unknown minor and refuse an
# unknown major. A file with no schema_version at all predates versioning
# and is treated as "pre-1.0".
RESULTS_SCHEMA_VERSION = "1.0"
```

Add to `ReportData` (alongside the other provenance fields):

```python
    schema_version: str | None = None
```

In `load_results`, in the `ReportData(...)` construction, add:

```python
        schema_version=raw.get("schema_version"),
```

In `src/vip/plugin.py`, import the constant near the existing `from vip import __version__` usage and add to the payload dict as its first key:

```python
        "schema_version": RESULTS_SCHEMA_VERSION,
```

Add the import at the top of `plugin.py` with the other `vip.reporting` imports:

```python
from vip.reporting import RESULTS_SCHEMA_VERSION
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_results_schema.py -v`
Expected: 3 passed

- [ ] Step 5: Run the full selftest suite for regressions

Run: `uv run pytest selftests/ -q`
Expected: all pass

- [ ] Step 6: Commit

```bash
git add src/vip/reporting.py src/vip/plugin.py selftests/test_results_schema.py
git commit -m "feat(reporting): add schema_version to results.json"
```

---

### Task 2: Per-test timestamps

Files:
- Modify: `src/vip/plugin.py` (helper + `pytest_runtest_logreport` results dict at `:1203-1216`)
- Modify: `src/vip/reporting.py` (`TestResult` fields, `load_results`)
- Test: `selftests/test_results_timestamps.py` (create)

Interfaces:
- Consumes: Task 1's additive-field pattern
- Produces: `TestResult.started_at: str | None`, `TestResult.finished_at: str | None` (UTC ISO 8601)

Background the implementer needs: `report.start` and `report.stop` are epoch floats on pytest's `TestReport`. They survive xdist worker-to-controller serialization (verified under `-n 0` and `-n 2`), which matters because only the controller writes the report (`plugin.py:1173-1176`). The collection site fires for `report.when == "call"` or a setup-phase skip (`plugin.py:1185`), so `started_at` is when the check itself began and excludes fixture setup. That is the intended semantic; do not try to widen it.

- [ ] Step 1: Write the failing test

Create `selftests/test_results_timestamps.py`:

```python
import json
from datetime import datetime


def test_results_carry_per_test_timestamps(pytester):
    pytester.makepyfile(
        test_stamp="""
        def test_passes():
            assert True

        import pytest

        @pytest.mark.skip(reason="deliberate")
        def test_skipped():
            pass
        """
    )
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")

    data = json.loads(report.read_text())
    assert data["results"], "expected at least one result"
    for entry in data["results"]:
        started, finished = entry["started_at"], entry["finished_at"]
        assert started is not None and finished is not None
        # Parses as ISO 8601 and is timezone-aware UTC.
        start_dt = datetime.fromisoformat(started)
        finish_dt = datetime.fromisoformat(finished)
        assert start_dt.tzinfo is not None
        assert start_dt.utcoffset().total_seconds() == 0
        assert start_dt <= finish_dt


def test_timestamps_absent_in_old_file_load_as_none(tmp_path):
    from vip.reporting import load_results

    p = tmp_path / "results.json"
    p.write_text(json.dumps({"results": [{"nodeid": "a.py::t", "outcome": "passed"}]}))
    result = load_results(p).results[0]
    assert result.started_at is None
    assert result.finished_at is None
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_results_timestamps.py -v`
Expected: FAIL with `KeyError: 'started_at'`

- [ ] Step 3: Write minimal implementation

In `src/vip/plugin.py`, add a module-level helper near the other `_extract_*` helpers:

```python
def _epoch_to_iso(value: float | None) -> str | None:
    """Convert a pytest report epoch float to a UTC ISO 8601 string.

    Returns None rather than raising for a missing or unrepresentable value:
    a provenance field is never worth failing a verification run over.
    """
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None
```

In the `results.append({...})` dict, add:

```python
                    "started_at": _epoch_to_iso(getattr(report, "start", None)),
                    "finished_at": _epoch_to_iso(getattr(report, "stop", None)),
```

In `src/vip/reporting.py`, add to `TestResult`:

```python
    # When this check began and ended, UTC ISO 8601, from pytest's report.start
    # and report.stop. This is the call phase, so it excludes fixture setup
    # (except for a setup-phase skip, where it is the setup start). None for a
    # results.json written before these fields existed.
    started_at: str | None = None
    finished_at: str | None = None
```

In `load_results`, inside the `TestResult(...)` construction:

```python
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_results_timestamps.py -v`
Expected: 2 passed

- [ ] Step 5: Verify timestamps survive xdist

Run: `uv run pytest selftests/test_results_timestamps.py -v -n 2`
Expected: 2 passed (the pytester subprocess is independent, but this confirms no controller/worker regression)

- [ ] Step 6: Commit

```bash
git add src/vip/plugin.py src/vip/reporting.py selftests/test_results_timestamps.py
git commit -m "feat(reporting): record per-test start and finish timestamps"
```

---

### Task 3: Execution attribution block

Files:
- Create: `src/vip/attribution.py`
- Modify: `src/vip/plugin.py` (`pytest_addoption`, payload)
- Modify: `src/vip/reporting.py` (`ReportData.execution`, `load_results`)
- Test: `selftests/test_attribution.py` (create)

Interfaces:
- Consumes: nothing
- Produces: `attribution.collect_execution_metadata(*, cwd: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]` returning keys `hostname`, `git`, `ci`; `attribution.redact_userinfo(url: str | None) -> str | None`; `ReportData.execution: dict | None`

Why a new module: this is self-contained, needs no pytest, and is the only part of the provenance work with meaningful branching (three CI providers, two git sources, URL redaction). Keeping it out of `plugin.py` makes it unit-testable without a pytest run.

Security requirement: CI checkouts routinely rewrite the origin remote to embed a credential (`https://x-access-token:ghs_...@github.com/org/repo`). `results.json` is an uploaded artifact — `plugin.py:1196-1201` already strips absolute paths for exactly this reason — so userinfo must be removed before recording. A remote that cannot be parsed is recorded as `None`, never passed through raw.

- [ ] Step 1: Write the failing test

Create `selftests/test_attribution.py`:

```python
import subprocess

import pytest

from vip.attribution import collect_execution_metadata


def _init_repo(path):
    def git(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (path / "f.txt").write_text("hello")
    git("add", "f.txt")
    git("commit", "-m", "initial")


def test_git_metadata_from_a_real_repo(tmp_path):
    _init_repo(tmp_path)
    meta = collect_execution_metadata(cwd=tmp_path, env={})
    assert meta["git"]["commit"] is not None
    assert len(meta["git"]["commit"]) == 40
    assert meta["git"]["dirty"] is False


def test_dirty_worktree_is_reported(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "f.txt").write_text("changed")
    assert collect_execution_metadata(cwd=tmp_path, env={})["git"]["dirty"] is True


def test_non_repo_yields_null_git(tmp_path):
    assert collect_execution_metadata(cwd=tmp_path, env={})["git"] is None


def test_no_ci_env_yields_null_ci(tmp_path):
    assert collect_execution_metadata(cwd=tmp_path, env={})["ci"] is None


def test_github_actions_run_url_is_composed(tmp_path):
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "posit-dev/vip",
        "GITHUB_JOB": "connect-smoke",
    }
    ci = collect_execution_metadata(cwd=tmp_path, env=env)["ci"]
    assert ci["provider"] == "github"
    assert ci["run_url"] == "https://github.com/posit-dev/vip/actions/runs/42"
    assert ci["job"] == "connect-smoke"


def test_gitlab_and_jenkins_are_recognized(tmp_path):
    gl = collect_execution_metadata(
        cwd=tmp_path, env={"GITLAB_CI": "true", "CI_JOB_URL": "https://gl/x/-/jobs/9"}
    )["ci"]
    assert gl["provider"] == "gitlab"
    assert gl["run_url"] == "https://gl/x/-/jobs/9"

    jk = collect_execution_metadata(
        cwd=tmp_path, env={"JENKINS_URL": "https://j/", "BUILD_URL": "https://j/job/x/7/"}
    )["ci"]
    assert jk["provider"] == "jenkins"
    assert jk["run_url"] == "https://j/job/x/7/"


def test_env_sha_takes_precedence_over_subprocess(tmp_path):
    _init_repo(tmp_path)
    env = {"GITHUB_SHA": "a" * 40, "GITHUB_REF_NAME": "feature/x"}
    meta = collect_execution_metadata(cwd=tmp_path, env=env)
    assert meta["git"]["commit"] == "a" * 40
    assert meta["git"]["branch"] == "feature/x"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://x-access-token:ghs_SECRET@github.com/o/r", "https://github.com/o/r"),
        ("https://user:pw@example.com:8443/o/r.git", "https://example.com:8443/o/r.git"),
        ("https://github.com/o/r", "https://github.com/o/r"),
        ("git@github.com:o/r.git", "github.com:o/r.git"),
        ("", None),
        (None, None),
    ],
)
def test_userinfo_is_redacted(raw, expected):
    from vip.attribution import redact_userinfo

    assert redact_userinfo(raw) == expected


def test_hostname_is_recorded(tmp_path):
    assert collect_execution_metadata(cwd=tmp_path, env={})["hostname"]
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_attribution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vip.attribution'`

- [ ] Step 3: Write minimal implementation

Create `src/vip/attribution.py`:

```python
"""Execution attribution for the results.json evidence record.

Answers "which pipeline execution, on which host, from which commit produced
this evidence" — the fields that make an automated test result attributable.

Every probe here degrades to None. A missing git binary, a detached worktree,
a non-repo working directory or an unrecognized CI system must never fail or
warn a verification run; provenance is not worth breaking a run over.
"""

from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_GIT_TIMEOUT_SECONDS = 5


def redact_userinfo(url: str | None) -> str | None:
    """Strip any userinfo component from a remote URL.

    CI checkouts rewrite the origin to embed a credential
    (``https://x-access-token:ghs_...@github.com/org/repo``). results.json is
    an uploaded artifact, so the credential must never reach it. Userinfo is
    never needed to identify a repository, so it is dropped unconditionally
    rather than pattern-matched against known token shapes.
    """
    if not url:
        return None
    if "://" not in url:
        # scp-style (git@host:org/repo.git). No password component, but drop
        # the user anyway so there is exactly one rule to reason about.
        return url.split("@", 1)[-1] if "@" in url else url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    netloc = parts.hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _git(args: list[str], cwd: Path) -> str | None:
    """Run a git command, returning stripped stdout, or None if it failed.

    An empty string is a valid successful result (``status --porcelain`` on a
    clean tree), so success-with-no-output must stay distinguishable from
    failure. Callers rely on that difference.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_metadata(cwd: Path, env: Mapping[str, str]) -> dict[str, Any] | None:
    commit = env.get("GITHUB_SHA") or _git(["rev-parse", "HEAD"], cwd)
    if not commit:
        return None
    status = _git(["status", "--porcelain"], cwd)
    return {
        "commit": commit,
        "branch": env.get("GITHUB_REF_NAME") or _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd),
        "dirty": bool(status) if status is not None else None,
        "remote": redact_userinfo(_git(["remote", "get-url", "origin"], cwd)),
    }


def _ci_metadata(env: Mapping[str, str]) -> dict[str, Any] | None:
    if env.get("GITHUB_ACTIONS") == "true":
        run_id = env.get("GITHUB_RUN_ID")
        repo = env.get("GITHUB_REPOSITORY")
        server = env.get("GITHUB_SERVER_URL") or "https://github.com"
        run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else None
        return {
            "provider": "github",
            "run_id": run_id,
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
            "run_url": run_url,
            "job": env.get("GITHUB_JOB"),
        }
    if env.get("GITLAB_CI") == "true":
        return {
            "provider": "gitlab",
            "run_id": env.get("CI_PIPELINE_ID"),
            "run_attempt": None,
            "run_url": env.get("CI_JOB_URL"),
            "job": env.get("CI_JOB_NAME"),
        }
    if env.get("JENKINS_URL"):
        return {
            "provider": "jenkins",
            "run_id": env.get("BUILD_NUMBER"),
            "run_attempt": None,
            "run_url": env.get("BUILD_URL"),
            "job": env.get("JOB_NAME"),
        }
    return None


def collect_execution_metadata(
    *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Collect host, git and CI attribution for the current run.

    ``hostname`` is the VIP runner's host, not the system under test. Anything
    rendering it must label it that way.
    """
    resolved_env = os.environ if env is None else env
    resolved_cwd = Path.cwd() if cwd is None else cwd
    return {
        "hostname": platform.node() or None,
        "git": _git_metadata(resolved_cwd, resolved_env),
        "ci": _ci_metadata(resolved_env),
    }
```

In `src/vip/plugin.py` `pytest_addoption`, add to the `vip` group:

```python
    group.addoption(
        "--vip-no-attribution",
        action="store_true",
        default=False,
        help="Omit host/git/CI attribution from results.json.",
    )
```

In the payload construction, add:

```python
        "execution": (
            None
            if session.config.getoption("--vip-no-attribution", default=False)
            else collect_execution_metadata()
        ),
```

with the import at the top of `plugin.py`:

```python
from vip.attribution import collect_execution_metadata
```

In `src/vip/reporting.py`, add to `ReportData`:

```python
    # Host / git / CI attribution; see vip.attribution. None when the run used
    # --vip-no-attribution, or for a results.json predating the field.
    execution: dict | None = None
```

and in `load_results`:

```python
        execution=raw.get("execution"),
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_attribution.py -v`
Expected: 9 passed

- [ ] Step 5: Write the opt-out and leak-regression test

Append to `selftests/test_attribution.py`:

```python
import json


def test_no_attribution_flag_omits_the_block(pytester):
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess(
        "--vip-report", str(report), "--vip-no-attribution", "-p", "no:cacheprovider"
    )
    assert json.loads(report.read_text())["execution"] is None


def test_credential_in_remote_never_reaches_the_file(pytester, monkeypatch):
    """Regression guard: assert the token is absent from the whole file."""
    secret = "ghs_THISMUSTNOTAPPEAR"
    subprocess.run(["git", "init"], cwd=pytester.path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://x-access-token:{secret}@github.com/o/r"],
        cwd=pytester.path,
        check=True,
        capture_output=True,
    )
    for key, value in (("user.email", "t@example.com"), ("user.name", "T"),
                       ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", key, value], cwd=pytester.path,
                       check=True, capture_output=True)
    pytester.makepyfile(test_x="def test_ok(): assert True")
    subprocess.run(["git", "add", "-A"], cwd=pytester.path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c"], cwd=pytester.path,
                   check=True, capture_output=True)

    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")
    assert secret not in report.read_text()
```

- [ ] Step 6: Run the new tests

Run: `uv run pytest selftests/test_attribution.py -v`
Expected: 11 passed

- [ ] Step 7: Commit

```bash
git add src/vip/attribution.py src/vip/plugin.py src/vip/reporting.py selftests/test_attribution.py
git commit -m "feat(reporting): attribute results to host, commit and CI run"
```

---

### Task 4: SHA-256 sidecar

Files:
- Modify: `src/vip/plugin.py:1312-1318` (write path)
- Test: `selftests/test_results_checksum.py` (create)

Interfaces:
- Consumes: nothing
- Produces: `report/results.json.sha256`, format `<hex>  results.json\n` (two spaces, `shasum -c` compatible)

Note: `results.json` is currently written via `p.write_text(json.dumps(...))` with no trailing newline, while `failures.json` appends one. The digest must cover the exact bytes on disk, so switch to an explicit encode-then-`write_bytes` and hash that same buffer. Do not re-serialize to compute the hash.

- [ ] Step 1: Write the failing test

Create `selftests/test_results_checksum.py`:

```python
import hashlib
import subprocess
import sys


def test_sidecar_matches_the_bytes_on_disk(pytester):
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")

    sidecar = report.parent / "results.json.sha256"
    assert sidecar.exists()

    expected = hashlib.sha256(report.read_bytes()).hexdigest()
    line = sidecar.read_text().strip()
    digest, name = line.split()
    assert digest == expected
    assert name == "results.json"


def test_sidecar_is_written_even_for_json_only_format(pytester):
    """The checksum is a property of the file, not an output format."""
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess(
        "--vip-report", str(report), "--vip-format", "json", "-p", "no:cacheprovider"
    )
    assert (report.parent / "results.json.sha256").exists()


def test_sidecar_verifies_with_shasum(pytester):
    if sys.platform.startswith("win"):
        return
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")
    proc = subprocess.run(
        ["shasum", "-a", "256", "-c", "results.json.sha256"],
        cwd=report.parent,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_results_checksum.py -v`
Expected: FAIL with `assert sidecar.exists()`

- [ ] Step 3: Write minimal implementation

Add `import hashlib` at the top of `src/vip/plugin.py`. Replace the write block:

```python
    try:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        warnings.warn(f"VIP: could not write report to {report_path}: {exc}", stacklevel=1)
        return
```

with:

```python
    try:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Hash the exact bytes written, not a re-serialization: the sidecar is
        # only useful if it verifies against the file actually on disk.
        data = json.dumps(payload, indent=2).encode("utf-8")
        p.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        # shasum -c compatible: "<hex>  <filename>". Written unconditionally
        # rather than gated on --vip-format, because the checksum is a property
        # of the evidence file rather than an output format.
        p.with_name(f"{p.name}.sha256").write_text(f"{digest}  {p.name}\n")
    except OSError as exc:
        warnings.warn(f"VIP: could not write report to {report_path}: {exc}", stacklevel=1)
        return
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_results_checksum.py -v`
Expected: 3 passed

- [ ] Step 5: Run the full selftest suite

Run: `uv run pytest selftests/ -q`
Expected: all pass

- [ ] Step 6: Commit

```bash
git add src/vip/plugin.py selftests/test_results_checksum.py
git commit -m "feat(reporting): write a sha256 sidecar next to results.json"
```

---

### Task 5: Gherkin parser collects all tags and ignores control tags for the marker

Files:
- Modify: `src/vip/gherkin.py:37-58` and the return dict
- Test: `selftests/test_gherkin_control_tags.py` (create)

Interfaces:
- Consumes: nothing
- Produces: `gherkin.CONTROL_TAG_PREFIX: str` (value `"control-"`); `parse_feature_file()` return dict gains a `tags: list[str]` key holding every tag in the file, `@` stripped

Why this comes before the plugin change: `gherkin.py` currently derives a feature's `marker` from the first token of the first tag line (`:56-57`), so `@control-x @connect` sets the marker to `control-x`. That value feeds the HTML report cards (`report_html.py:241`), `scripts/generate-test-catalog.py:46` and `scripts/generate-feature-matrix.py:142`. Task 6 also needs a tag list this parser does not currently return.

- [ ] Step 1: Write the failing test

Create `selftests/test_gherkin_control_tags.py`:

```python
from vip.gherkin import CONTROL_TAG_PREFIX, parse_feature_file

FEATURE = """@control-cfr-11-10-e @connect
Feature: Audit trail
  Scenario: Publish is recorded
    Given Connect is reachable
"""

PRODUCT_FIRST = """@connect @control-cfr-11-10-e
Feature: Audit trail
  Scenario: Publish is recorded
    Given Connect is reachable
"""


def test_control_tag_does_not_become_the_marker(tmp_path):
    """Tag order inside a feature file must not change the derived marker."""
    f = tmp_path / "t.feature"
    f.write_text(FEATURE)
    assert parse_feature_file(f)["marker"] == "connect"


def test_product_first_ordering_is_unchanged(tmp_path):
    f = tmp_path / "t.feature"
    f.write_text(PRODUCT_FIRST)
    assert parse_feature_file(f)["marker"] == "connect"


def test_all_tags_are_collected(tmp_path):
    f = tmp_path / "t.feature"
    f.write_text(FEATURE)
    assert set(parse_feature_file(f)["tags"]) == {"control-cfr-11-10-e", "connect"}


def test_scenario_level_tags_are_collected(tmp_path):
    f = tmp_path / "t.feature"
    f.write_text(
        "@connect\n"
        "Feature: F\n"
        "  @control-access-control\n"
        "  Scenario: S\n"
        "    Given x\n"
    )
    parsed = parse_feature_file(f)
    assert parsed["marker"] == "connect"
    assert "control-access-control" in parsed["tags"]


def test_prefix_constant():
    assert CONTROL_TAG_PREFIX == "control-"
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_gherkin_control_tags.py -v`
Expected: FAIL with `ImportError: cannot import name 'CONTROL_TAG_PREFIX'`

- [ ] Step 3: Write minimal implementation

In `src/vip/gherkin.py`, add below `_STEP_PREFIXES`:

```python
# Gherkin tags of the form @control-<slug> map a scenario to a compliance
# control. They are deliberately excluded from the derived feature marker:
# that value feeds the HTML report cards and the generated test catalog and
# feature matrix, so a control tag written before the product tag would
# otherwise silently mislabel the feature.
CONTROL_TAG_PREFIX = "control-"
```

Add `tags: list[str] = []` beside the other accumulators, and replace the tag-line branch:

```python
        # Tag line — first non-control tag becomes the marker.
        if line.startswith("@"):
            line_tags = [tok.lstrip("@") for tok in line.split() if tok.startswith("@")]
            tags.extend(line_tags)
            if not marker:
                for tag in line_tags:
                    if not tag.startswith(CONTROL_TAG_PREFIX):
                        marker = tag
                        break
            continue
```

Add `"tags": tags,` to the returned dict, and document the new key in the docstring's Returns section:

```
    dict with keys: ``title``, ``description``, ``marker``, ``tags``,
    ``file``, ``scenarios`` (list of dicts with ``title`` and ``steps``).
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_gherkin_control_tags.py -v`
Expected: 5 passed

- [ ] Step 5: Verify the catalog generators still work

Run: `uv run python scripts/generate-test-catalog.py && uv run python scripts/generate-feature-matrix.py`
Expected: both exit 0. Per the project memory these outputs are gitignored and generated — do not commit them.

- [ ] Step 6: Commit

```bash
git add src/vip/gherkin.py selftests/test_gherkin_control_tags.py
git commit -m "fix(gherkin): keep control tags out of the derived feature marker"
```

---

### Task 6: Pre-register control markers so strict-marker CI passes

Files:
- Modify: `src/vip/plugin.py::pytest_configure` (after the marker registrations at `:176-209`)
- Test: `selftests/test_control_marker_registration.py` (create)

Interfaces:
- Consumes: `gherkin.CONTROL_TAG_PREFIX`, `gherkin.parse_feature_file` (Task 5)
- Produces: control tags registered as pytest markers before collection

Background: pytest punishes unregistered marks two different ways. By default `getattr(pytest.mark, tag)` raises `PytestUnknownMarkWarning` (`_pytest/mark/structures.py:628`), fatal under `-W error::pytest.PytestUnknownMarkWarning`. Under `--strict-markers` it does not warn at all — it calls `fail()` and aborts collection with `'control-x' not found in `markers` configuration option`. Verified against pytest 9.1.1. A `filterwarnings` ignore cannot reach the strict path, which is why registration is the fix rather than suppression. Registration also removes the warning, so both failure modes are covered by one mechanism.

- [ ] Step 1: Write the failing test

Create `selftests/test_control_marker_registration.py`:

```python
import json

FEATURE = """@connect @control-cfr-11-10-e
Feature: Audit trail
  Scenario: Publish is recorded
    Given a thing
"""

STEPS = """
from pytest_bdd import given, scenario


@scenario("t.feature", "Publish is recorded")
def test_tagged():
    pass


@given("a thing")
def a_thing():
    pass
"""


def _write_suite(pytester):
    (pytester.path / "t.feature").write_text(FEATURE)
    pytester.makepyfile(test_t=STEPS)
    (pytester.path / "vip.toml").write_text('[connect]\nurl = "https://c.example.com"\n')


def test_collects_under_strict_markers(pytester):
    _write_suite(pytester)
    result = pytester.runpytest_subprocess(
        "--vip-config", "vip.toml", "--strict-markers", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=1)


def test_collects_under_warnings_as_errors(pytester):
    _write_suite(pytester)
    result = pytester.runpytest_subprocess(
        "--vip-config",
        "vip.toml",
        "-W",
        "error::pytest.PytestUnknownMarkWarning",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=1)


def test_collects_under_both_together(pytester):
    _write_suite(pytester)
    result = pytester.runpytest_subprocess(
        "--vip-config",
        "vip.toml",
        "--strict-markers",
        "-W",
        "error::pytest.PytestUnknownMarkWarning",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=1)


def test_control_tags_still_reach_results_json(pytester):
    """Registration must not cost us the evidence it exists to preserve."""
    _write_suite(pytester)
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess(
        "--vip-config", "vip.toml", "--vip-report", str(report), "-p", "no:cacheprovider"
    )
    markers = json.loads(report.read_text())["results"][0]["markers"]
    assert "control-cfr-11-10-e" in markers
    assert "connect" in markers
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_control_marker_registration.py -v`
Expected: `test_collects_under_strict_markers` FAILS with `'control-cfr-11-10-e' not found in `markers` configuration option`

- [ ] Step 3: Write minimal implementation

In `src/vip/plugin.py`, add the import:

```python
from vip.gherkin import CONTROL_TAG_PREFIX, parse_feature_file
```

Add these module-level helpers:

```python
def _feature_roots(config: pytest.Config) -> list[Path]:
    """Directories pytest is about to collect, plus any extension directories.

    Scanning these rather than walking rootpath keeps the pre-scan cheap in a
    large monorepo and avoids registering controls from feature files that are
    not part of this run.
    """
    roots: list[Path] = []
    for arg in config.args:
        candidate = Path(str(arg).split("::")[0])
        roots.append(candidate if candidate.is_absolute() else Path(config.rootpath) / candidate)
    roots.extend(Path(d) for d in (config.getoption("--vip-extensions", default=[]) or []))
    return roots or [Path(config.rootpath)]


def _discover_control_tags(config: pytest.Config) -> set[str]:
    """Collect every @control-* tag from the feature files about to be collected."""
    tags: set[str] = set()
    for root in _feature_roots(config):
        try:
            if root.is_file():
                features = [root] if root.suffix == ".feature" else []
            else:
                features = sorted(root.rglob("*.feature"))
        except OSError:
            continue
        for feature in features:
            try:
                parsed = parse_feature_file(feature)
            except (OSError, UnicodeDecodeError):
                continue
            tags.update(t for t in parsed["tags"] if t.startswith(CONTROL_TAG_PREFIX))
    return tags
```

In `pytest_configure`, immediately after the last `addinivalue_line("markers", ...)` call:

```python
    # Compliance control tags (@control-<slug>) become pytest markers via
    # pytest-bdd's default pytest_bdd_apply_tag hook. Their slugs are chosen by
    # the customer, so they cannot be registered by name ahead of time -- but an
    # unregistered mark warns by default and aborts collection outright under
    # --strict-markers, which regulated CI is likely to enable. Registering the
    # tags we are about to collect satisfies both paths at once.
    for tag in sorted(_discover_control_tags(config)):
        config.addinivalue_line("markers", f"{tag}: compliance control tag")
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_control_marker_registration.py -v`
Expected: 4 passed

- [ ] Step 5: Confirm no regression in the existing suite

Run: `uv run pytest selftests/ -q`
Expected: all pass

- [ ] Step 6: Commit

```bash
git add src/vip/plugin.py selftests/test_control_marker_registration.py
git commit -m "feat(plugin): register control tags as markers before collection"
```

---

### Task 7: Control list model and loader

Files:
- Create: `src/vip/traceability.py`
- Test: `selftests/test_traceability_controls.py` (create)

Interfaces:
- Consumes: nothing
- Produces: `ControlSpec` dataclass (fields `control_id`, `description`, `reference`, `risk`, `verification`, `responsibility`, `notes`); `load_controls(path) -> dict[str, ControlSpec]`; `ControlListError`

Deviation from the spec, deliberate: the spec places `build_traceability_matrix` in `reporting.py`. This plan puts the whole traceability feature in a new `src/vip/traceability.py` instead. `reporting.py` already holds the data model plus the JSON, JUnit and SARIF writers, and this codebase's own precedent is to split — `report_html.py` exists as "reporting.py's testable rendering sibling" per CLAUDE.md. Same reasoning, same shape.

- [ ] Step 1: Write the failing test

Create `selftests/test_traceability_controls.py`:

```python
import pytest

from vip.traceability import ControlListError, load_controls

FULL = """
[controls.cfr-11-10-e]
description = "Secure, computer-generated, time-stamped audit trails"
reference = "21 CFR 11.10(e)"
risk = "high"
verification = "automated"
responsibility = "shared"
notes = "Retention duration is a customer configuration decision."

[controls.training]
description = "Personnel training records"
verification = "procedural"
responsibility = "customer"
"""


def test_loads_all_fields(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text(FULL)
    controls = load_controls(p)

    audit = controls["cfr-11-10-e"]
    assert audit.description.startswith("Secure")
    assert audit.reference == "21 CFR 11.10(e)"
    assert audit.risk == "high"
    assert audit.verification == "automated"
    assert audit.responsibility == "shared"
    assert audit.notes


def test_optional_fields_default(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "only required key"\n')
    spec = load_controls(p)["x"]
    assert spec.reference is None
    assert spec.risk is None
    assert spec.responsibility is None
    assert spec.verification == "automated"


def test_missing_description_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\nrisk = "high"\n')
    with pytest.raises(ControlListError, match="description"):
        load_controls(p)


def test_unknown_verification_value_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('[controls.x]\ndescription = "d"\nverification = "vibes"\n')
    with pytest.raises(ControlListError, match="verification"):
        load_controls(p)


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(ControlListError, match="not found"):
        load_controls(tmp_path / "nope.toml")


def test_missing_controls_table_is_an_error(tmp_path):
    p = tmp_path / "controls.toml"
    p.write_text('title = "wrong shape"\n')
    with pytest.raises(ControlListError, match="controls"):
        load_controls(p)
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_traceability_controls.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vip.traceability'`

- [ ] Step 3: Write minimal implementation

Create `src/vip/traceability.py`:

```python
"""Traceability matrix: join compliance controls against tagged test results.

VIP stays regulation-agnostic. The control list is supplied by whoever owns the
regulatory mapping; nothing here interprets ``reference``, ``risk`` or
``responsibility`` beyond carrying them through to the output.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# Matrix output schema, versioned independently of results.json.
MATRIX_SCHEMA_VERSION = "1.0"

VERIFICATION_VALUES = frozenset({"automated", "manual", "procedural"})


class ControlListError(Exception):
    """Raised when a controls.toml file is missing or malformed."""


@dataclass
class ControlSpec:
    control_id: str
    description: str
    reference: str | None = None
    risk: str | None = None
    # "automated" controls are expected to be covered by a tagged scenario.
    # "manual" and "procedural" ones are reported as not verifiable by
    # automated test rather than as coverage gaps.
    verification: str = "automated"
    responsibility: str | None = None
    notes: str | None = None


def load_controls(path: str | Path) -> dict[str, ControlSpec]:
    """Load a controls.toml file into ControlSpec objects keyed by control id."""
    p = Path(path)
    if not p.is_file():
        raise ControlListError(f"control list not found: {p}")
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ControlListError(f"could not read control list {p}: {exc}") from exc

    table = raw.get("controls")
    if not isinstance(table, dict) or not table:
        raise ControlListError(f"{p} has no [controls] table")

    controls: dict[str, ControlSpec] = {}
    for control_id, body in table.items():
        if not isinstance(body, dict):
            raise ControlListError(f"[controls.{control_id}] must be a table")
        description = body.get("description")
        if not description:
            raise ControlListError(f"[controls.{control_id}] is missing a description")
        verification = body.get("verification", "automated")
        if verification not in VERIFICATION_VALUES:
            raise ControlListError(
                f"[controls.{control_id}] has verification={verification!r};"
                f" expected one of {sorted(VERIFICATION_VALUES)}"
            )
        controls[control_id] = ControlSpec(
            control_id=control_id,
            description=description,
            reference=body.get("reference"),
            risk=body.get("risk"),
            verification=verification,
            responsibility=body.get("responsibility"),
            notes=body.get("notes"),
        )
    return controls
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_traceability_controls.py -v`
Expected: 6 passed

- [ ] Step 5: Commit

```bash
git add src/vip/traceability.py selftests/test_traceability_controls.py
git commit -m "feat(traceability): add the control list model and loader"
```

---

### Task 8: Build the traceability matrix

Files:
- Modify: `src/vip/traceability.py`
- Test: `selftests/test_traceability_matrix.py` (create)

Interfaces:
- Consumes: `ControlSpec` (Task 7); `ReportData`/`TestResult` including `started_at`/`finished_at` (Task 2) and `execution`/`schema_version` (Tasks 1, 3)
- Produces: `ControlMatch`, `ControlEntry`, `TraceabilityMatrix` dataclasses; `build_traceability_matrix(data, controls, tag_prefix="control-") -> TraceabilityMatrix`

Coverage is three-valued. `covered` when at least one scenario matched. `not_automatable` when no scenario matched and `verification` is `manual` or `procedural`. `gap` when no scenario matched and `verification` is `automated`. Conflating the last two is the single most misleading thing this export could do: a control nobody can automate is not the same as a control someone forgot to test.

- [ ] Step 1: Write the failing test

Create `selftests/test_traceability_matrix.py`:

```python
from vip.reporting import ReportData, TestResult
from vip.traceability import ControlSpec, build_traceability_matrix


def _result(nodeid, markers, outcome="passed", **kw):
    return TestResult(
        nodeid=nodeid,
        outcome=outcome,
        markers=markers,
        scenario_title=kw.pop("title", "A scenario"),
        started_at="2026-08-28T12:00:00+00:00",
        finished_at="2026-08-28T12:00:01+00:00",
        **kw,
    )


def _controls(**kw):
    return {cid: ControlSpec(control_id=cid, description=f"desc {cid}", **opts)
            for cid, opts in kw.items()}


def test_covered_control_lists_its_scenarios():
    data = ReportData(results=[_result("t.py::a", ["connect", "control-x"], title="Scenario A")])
    matrix = build_traceability_matrix(data, _controls(x={}))
    entry = matrix.entries[0]
    assert entry.coverage == "covered"
    assert entry.matches[0].scenario_title == "Scenario A"
    assert entry.matches[0].status == "passed"
    assert entry.matches[0].started_at == "2026-08-28T12:00:00+00:00"


def test_uncovered_automated_control_is_a_gap():
    matrix = build_traceability_matrix(ReportData(results=[]), _controls(x={}))
    assert matrix.entries[0].coverage == "gap"
    assert matrix.gap_count == 1


def test_procedural_control_is_not_a_gap():
    controls = _controls(x={"verification": "procedural"})
    matrix = build_traceability_matrix(ReportData(results=[]), controls)
    assert matrix.entries[0].coverage == "not_automatable"
    assert matrix.gap_count == 0


def test_one_control_satisfied_by_several_scenarios():
    data = ReportData(
        results=[
            _result("t.py::a", ["control-x"], title="A"),
            _result("t.py::b", ["control-x"], title="B"),
        ]
    )
    entry = build_traceability_matrix(data, _controls(x={})).entries[0]
    assert [m.scenario_title for m in entry.matches] == ["A", "B"]


def test_one_scenario_satisfies_several_controls():
    data = ReportData(results=[_result("t.py::a", ["control-x", "control-y"])])
    matrix = build_traceability_matrix(data, _controls(x={}, y={}))
    assert all(e.coverage == "covered" for e in matrix.entries)


def test_unrecognized_tag_is_reported():
    data = ReportData(results=[_result("t.py::a", ["control-typo"])])
    matrix = build_traceability_matrix(data, _controls(x={}))
    assert matrix.unrecognized_tags == ["control-typo"]


def test_failure_detail_is_carried():
    data = ReportData(
        results=[
            _result("t.py::a", ["control-x"], outcome="failed", concise_error="boom"),
        ]
    )
    match = build_traceability_matrix(data, _controls(x={})).entries[0].matches[0]
    assert match.status == "failed"
    assert match.detail == "boom"


def test_skip_reason_is_carried():
    data = ReportData(
        results=[
            _result("t.py::a", ["control-x"], outcome="skipped", skip_reason="not configured"),
        ]
    )
    assert build_traceability_matrix(data, _controls(x={})).entries[0].matches[0].detail == (
        "not configured"
    )


def test_na_version_status_is_distinct():
    data = ReportData(
        results=[_result("t.py::a", ["control-x"], outcome="skipped", na_version=True)]
    )
    assert build_traceability_matrix(data, _controls(x={})).entries[0].matches[0].status == (
        "na_version"
    )


def test_entries_and_matches_are_sorted_deterministically():
    data = ReportData(
        results=[
            _result("t.py::z", ["control-b"], title="Z"),
            _result("t.py::a", ["control-b"], title="A"),
        ]
    )
    matrix = build_traceability_matrix(data, _controls(b={}, a={}))
    assert [e.control.control_id for e in matrix.entries] == ["a", "b"]
    b_entry = next(e for e in matrix.entries if e.control.control_id == "b")
    assert [m.nodeid for m in b_entry.matches] == ["t.py::a", "t.py::z"]


def test_custom_tag_prefix():
    data = ReportData(results=[_result("t.py::a", ["req-x"])])
    matrix = build_traceability_matrix(data, _controls(x={}), tag_prefix="req-")
    assert matrix.entries[0].coverage == "covered"


def test_provenance_is_carried_from_the_report():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        schema_version="1.0",
        basic_mode=True,
        execution={"hostname": "runner-1", "git": None, "ci": None},
    )
    prov = build_traceability_matrix(data, _controls(x={})).provenance
    assert prov["vip_version"] == "2026.8.3"
    assert prov["basic_mode"] is True
    assert prov["execution"]["hostname"] == "runner-1"
    assert prov["results_schema_version"] == "1.0"
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_traceability_matrix.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_traceability_matrix'`

- [ ] Step 3: Write minimal implementation

Add `from vip.reporting import ReportData` to the imports at the top of
`src/vip/traceability.py` (Task 10 extends this same line to also import
`RESULTS_SCHEMA_VERSION`), then append:

```python
@dataclass
class ControlMatch:
    """One scenario that carries a control's tag."""

    nodeid: str
    scenario_title: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    detail: str | None


@dataclass
class ControlEntry:
    control: ControlSpec
    matches: list[ControlMatch] = field(default_factory=list)
    # "covered" | "gap" | "not_automatable"
    coverage: str = "gap"


@dataclass
class TraceabilityMatrix:
    entries: list[ControlEntry] = field(default_factory=list)
    unrecognized_tags: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    schema_version: str = MATRIX_SCHEMA_VERSION

    @property
    def gap_count(self) -> int:
        return sum(1 for e in self.entries if e.coverage == "gap")

    @property
    def covered_count(self) -> int:
        return sum(1 for e in self.entries if e.coverage == "covered")


def _provenance(data: ReportData) -> dict:
    products = {
        p.name: {"url": p.url, "version": p.version, "configured": p.configured}
        for p in data.products
    }
    return {
        "generated_at": data.generated_at,
        "deployment_name": data.deployment_name,
        "vip_version": data.vip_version,
        "results_schema_version": data.schema_version,
        "exit_status": data.exit_status,
        # basic_mode is surfaced deliberately: a matrix built from a
        # `vip verify --basic` run omits every @slow scenario and would
        # otherwise assert coverage that was never exercised.
        "basic_mode": data.basic_mode,
        "execution": data.execution,
        # Describes the VIP runner, not the system under test. The products
        # table below identifies the system under test.
        "runner_python_version": data.python_version,
        "runner_platform": data.platform,
        "products": products,
    }


def build_traceability_matrix(
    data: ReportData,
    controls: dict[str, ControlSpec],
    tag_prefix: str = "control-",
) -> TraceabilityMatrix:
    """Join control definitions against tagged test results.

    Sorted deterministically -- by control id, then by nodeid within a control
    -- so the same results.json and control list always produce byte-identical
    output for a downstream renderer to diff.
    """
    by_tag: dict[str, list[ControlMatch]] = {}
    seen_tags: set[str] = set()
    for result in data.results:
        for marker in result.markers:
            if not marker.startswith(tag_prefix):
                continue
            seen_tags.add(marker)
            by_tag.setdefault(marker, []).append(
                ControlMatch(
                    nodeid=result.nodeid,
                    scenario_title=result.scenario_title,
                    status=result.status,
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    detail=result.concise_error or result.skip_reason,
                )
            )

    entries: list[ControlEntry] = []
    for control_id in sorted(controls):
        control = controls[control_id]
        matches = sorted(by_tag.get(f"{tag_prefix}{control_id}", []), key=lambda m: m.nodeid)
        if matches:
            coverage = "covered"
        elif control.verification != "automated":
            coverage = "not_automatable"
        else:
            coverage = "gap"
        entries.append(ControlEntry(control=control, matches=matches, coverage=coverage))

    known = {f"{tag_prefix}{cid}" for cid in controls}
    return TraceabilityMatrix(
        entries=entries,
        unrecognized_tags=sorted(seen_tags - known),
        provenance=_provenance(data),
    )
```

Note the `field` import: `ControlEntry` and `TraceabilityMatrix` use
`field(default_factory=...)`, which Task 7 already imported from `dataclasses`.

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_traceability_matrix.py -v`
Expected: 12 passed

- [ ] Step 5: Commit

```bash
git add src/vip/traceability.py selftests/test_traceability_matrix.py
git commit -m "feat(traceability): build the control-to-scenario matrix"
```

---

### Task 9: Render the matrix as CSV and JSON

Files:
- Modify: `src/vip/traceability.py`
- Test: `selftests/test_traceability_render.py` (create)

Interfaces:
- Consumes: `TraceabilityMatrix` (Task 8)
- Produces: `render_csv(matrix) -> str`, `render_json(matrix) -> str`

CSV columns, in order: `control_id`, `description`, `reference`, `risk`, `verification`, `responsibility`, `coverage`, `scenario`, `nodeid`, `status`, `started_at`, `finished_at`, `detail`, `notes`. A control with several matches emits one row per match. A control with no matches emits a single row with empty scenario columns. `duration` is deliberately absent: it is performance noise that varies run to run without carrying evidentiary value, unlike `started_at`.

- [ ] Step 1: Write the failing test

Create `selftests/test_traceability_render.py`:

```python
import csv
import io
import json

from vip.reporting import ReportData, TestResult
from vip.traceability import (
    ControlSpec,
    build_traceability_matrix,
    render_csv,
    render_json,
)

CSV_COLUMNS = [
    "control_id", "description", "reference", "risk", "verification",
    "responsibility", "coverage", "scenario", "nodeid", "status",
    "started_at", "finished_at", "detail", "notes",
]


def _matrix():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[
            TestResult(
                nodeid="t.py::a",
                outcome="passed",
                markers=["control-x"],
                scenario_title="Scenario A",
                started_at="2026-08-28T12:00:00+00:00",
                finished_at="2026-08-28T12:00:01+00:00",
            )
        ],
    )
    controls = {
        "x": ControlSpec("x", "Audit trail", reference="21 CFR 11.10(e)", risk="high"),
        "y": ControlSpec("y", "Training records", verification="procedural"),
    }
    return build_traceability_matrix(data, controls)


def test_csv_has_the_expected_header():
    reader = csv.reader(io.StringIO(render_csv(_matrix())))
    assert next(reader) == CSV_COLUMNS


def test_csv_emits_one_row_per_match_and_one_for_a_gap():
    rows = list(csv.DictReader(io.StringIO(render_csv(_matrix()))))
    assert len(rows) == 2
    covered = next(r for r in rows if r["control_id"] == "x")
    assert covered["scenario"] == "Scenario A"
    assert covered["status"] == "passed"
    assert covered["coverage"] == "covered"

    procedural = next(r for r in rows if r["control_id"] == "y")
    assert procedural["coverage"] == "not_automatable"
    assert procedural["scenario"] == ""
    assert procedural["nodeid"] == ""


def test_csv_is_byte_identical_across_invocations():
    m = _matrix()
    assert render_csv(m) == render_csv(m)
    assert render_csv(_matrix()) == render_csv(_matrix())


def test_json_carries_provenance_and_schema_version():
    payload = json.loads(render_json(_matrix()))
    assert payload["schema_version"] == "1.0"
    assert payload["provenance"]["vip_version"] == "2026.8.3"
    assert payload["summary"]["gaps"] == 0
    assert payload["summary"]["covered"] == 1
    assert payload["summary"]["not_automatable"] == 1


def test_json_is_byte_identical_across_invocations():
    assert render_json(_matrix()) == render_json(_matrix())


def test_json_round_trips():
    payload = json.loads(render_json(_matrix()))
    entry = next(e for e in payload["controls"] if e["control_id"] == "x")
    assert entry["matches"][0]["nodeid"] == "t.py::a"
    assert entry["reference"] == "21 CFR 11.10(e)"
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_traceability_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_csv'`

- [ ] Step 3: Write minimal implementation

Add `import csv`, `import io` and `import json` to the imports in `src/vip/traceability.py`, then append:

```python
CSV_COLUMNS = [
    "control_id",
    "description",
    "reference",
    "risk",
    "verification",
    "responsibility",
    "coverage",
    "scenario",
    "nodeid",
    "status",
    "started_at",
    "finished_at",
    "detail",
    "notes",
]


def _control_columns(entry: ControlEntry) -> dict:
    c = entry.control
    return {
        "control_id": c.control_id,
        "description": c.description,
        "reference": c.reference or "",
        "risk": c.risk or "",
        "verification": c.verification,
        "responsibility": c.responsibility or "",
        "coverage": entry.coverage,
        "notes": c.notes or "",
    }


def render_csv(matrix: TraceabilityMatrix) -> str:
    """Render the matrix as CSV: one row per control/scenario pair.

    A control with no matching scenario still gets a row, with the scenario
    columns empty, so a coverage gap is visible rather than absent.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for entry in matrix.entries:
        base = _control_columns(entry)
        if not entry.matches:
            writer.writerow(
                {**base, "scenario": "", "nodeid": "", "status": "",
                 "started_at": "", "finished_at": "", "detail": ""}
            )
            continue
        for match in entry.matches:
            writer.writerow(
                {
                    **base,
                    "scenario": match.scenario_title or "",
                    "nodeid": match.nodeid,
                    "status": match.status,
                    "started_at": match.started_at or "",
                    "finished_at": match.finished_at or "",
                    "detail": match.detail or "",
                }
            )
    return buf.getvalue()


def render_json(matrix: TraceabilityMatrix) -> str:
    """Render the matrix as JSON, carrying the full provenance block."""
    payload = {
        "schema_version": matrix.schema_version,
        "provenance": matrix.provenance,
        "summary": {
            "total": len(matrix.entries),
            "covered": matrix.covered_count,
            "gaps": matrix.gap_count,
            "not_automatable": sum(
                1 for e in matrix.entries if e.coverage == "not_automatable"
            ),
        },
        "unrecognized_tags": matrix.unrecognized_tags,
        "controls": [
            {
                **_control_columns(entry),
                "matches": [
                    {
                        "nodeid": m.nodeid,
                        "scenario": m.scenario_title,
                        "status": m.status,
                        "started_at": m.started_at,
                        "finished_at": m.finished_at,
                        "detail": m.detail,
                    }
                    for m in entry.matches
                ],
            }
            for entry in matrix.entries
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"
```

- [ ] Step 4: Run test to verify it passes

Run: `uv run pytest selftests/test_traceability_render.py -v`
Expected: 6 passed

- [ ] Step 5: Commit

```bash
git add src/vip/traceability.py selftests/test_traceability_render.py
git commit -m "feat(traceability): render the matrix as csv and json"
```

---

### Task 10: `vip trace` CLI

Files:
- Modify: `src/vip/cli.py` (add `run_trace`, the subparser near the `scaffold` block at `:1892-1934`, and the `subcommand_parsers` map at `:1936-1946`)
- Modify: `src/vip/traceability.py` (checksum verification, schema gate)
- Test: `selftests/test_trace_cli.py` (create)

Interfaces:
- Consumes: `load_controls`, `build_traceability_matrix`, `render_csv`, `render_json` (Tasks 7-9); `load_results` (existing)
- Produces: `cli.run_trace(args: argparse.Namespace) -> None`; `traceability.verify_results_checksum(path: str | Path) -> str | None`; `traceability.check_results_schema(schema_version: str | None) -> None`; `traceability.ResultsIntegrityError`

Behaviour:
- Unknown schema major is a hard error naming both versions. Unknown minor proceeds. A missing `schema_version` (pre-1.0) proceeds.
- A `.sha256` sidecar next to the results file is verified. A mismatch is a hard error, not a warning: a checksum mismatch on a compliance artifact is precisely the condition that must not be papered over. A missing sidecar is fine — older runs have none.
- Unrecognized control tags print to stderr as a warning and do not fail the command; they catch typos without blocking an otherwise valid export.

- [ ] Step 1: Write the failing test

Create `selftests/test_trace_cli.py`:

```python
import hashlib
import json
import subprocess
import sys

CONTROLS = """
[controls.x]
description = "Audit trail"
reference = "21 CFR 11.10(e)"

[controls.y]
description = "Training records"
verification = "procedural"
"""


def _results(tmp_path, schema_version="1.0", write_sidecar=True):
    payload = {
        "schema_version": schema_version,
        "generated_at": "2026-08-28T12:00:00+00:00",
        "vip_version": "2026.8.3",
        "results": [
            {
                "nodeid": "t.py::a",
                "outcome": "passed",
                "markers": ["connect", "control-x"],
                "scenario_title": "Scenario A",
                "started_at": "2026-08-28T12:00:00+00:00",
                "finished_at": "2026-08-28T12:00:01+00:00",
            }
        ],
    }
    if schema_version is None:
        payload.pop("schema_version")
    p = tmp_path / "results.json"
    data = json.dumps(payload, indent=2).encode()
    p.write_bytes(data)
    if write_sidecar:
        p.with_name("results.json.sha256").write_text(
            f"{hashlib.sha256(data).hexdigest()}  results.json\n"
        )
    controls = tmp_path / "controls.toml"
    controls.write_text(CONTROLS)
    return p, controls


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "vip.cli", "trace", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_csv_to_stdout(tmp_path):
    results, controls = _results(tmp_path)
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("control_id,description,")
    assert "Scenario A" in proc.stdout


def test_json_format(tmp_path):
    results, controls = _results(tmp_path)
    proc = _run("--results", str(results), "--controls", str(controls), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["covered"] == 1
    assert payload["summary"]["not_automatable"] == 1


def test_output_to_file(tmp_path):
    results, controls = _results(tmp_path)
    out = tmp_path / "matrix.csv"
    proc = _run("--results", str(results), "--controls", str(controls), "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.read_text().startswith("control_id,")


def test_tampered_results_file_is_rejected(tmp_path):
    results, controls = _results(tmp_path)
    results.write_text(results.read_text().replace("passed", "failed"))
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "checksum" in proc.stderr.lower()


def test_missing_sidecar_is_allowed(tmp_path):
    results, controls = _results(tmp_path, write_sidecar=False)
    assert _run("--results", str(results), "--controls", str(controls)).returncode == 0


def test_pre_1_0_results_are_accepted(tmp_path):
    results, controls = _results(tmp_path, schema_version=None)
    assert _run("--results", str(results), "--controls", str(controls)).returncode == 0


def test_unknown_major_schema_is_rejected(tmp_path):
    results, controls = _results(tmp_path, schema_version="2.0")
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "2.0" in proc.stderr


def test_unknown_minor_schema_is_accepted(tmp_path):
    results, controls = _results(tmp_path, schema_version="1.7")
    assert _run("--results", str(results), "--controls", str(controls)).returncode == 0


def test_unrecognized_tag_warns_without_failing(tmp_path):
    results, controls = _results(tmp_path)
    payload = json.loads(results.read_text())
    payload["results"][0]["markers"].append("control-typo")
    data = json.dumps(payload, indent=2).encode()
    results.write_bytes(data)
    results.with_name("results.json.sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  results.json\n"
    )
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode == 0
    assert "control-typo" in proc.stderr


def test_missing_control_file_errors_clearly(tmp_path):
    results, _ = _results(tmp_path)
    proc = _run("--results", str(results), "--controls", str(tmp_path / "nope.toml"))
    assert proc.returncode != 0
    assert "not found" in proc.stderr
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_trace_cli.py -v`
Expected: FAIL — `invalid choice: 'trace'`

- [ ] Step 3: Add checksum and schema helpers

Append to `src/vip/traceability.py` (add `import hashlib` to the imports):

```python
class ResultsIntegrityError(Exception):
    """Raised when a results file fails checksum or schema validation."""


def verify_results_checksum(path: str | Path) -> str | None:
    """Verify a results file against its .sha256 sidecar.

    Returns the digest of the file. Raises if a sidecar exists and disagrees.
    A missing sidecar is not an error: results files written before the
    sidecar existed have none.

    This is tamper-evidence within a trusted pipeline, not tamper-proofing --
    anyone who can edit the results file can regenerate the sidecar. It catches
    corruption, truncated uploads and casual editing.
    """
    p = Path(path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    sidecar = p.with_name(f"{p.name}.sha256")
    if not sidecar.is_file():
        return digest
    recorded = sidecar.read_text().split()
    if recorded and recorded[0] != digest:
        raise ResultsIntegrityError(
            f"checksum mismatch for {p}: sidecar records {recorded[0]}, file hashes to {digest}"
        )
    return digest


def check_results_schema(schema_version: str | None) -> None:
    """Refuse an unknown major schema version; accept an unknown minor.

    A file with no schema_version predates versioning and is accepted.
    """
    if not schema_version:
        return
    theirs = schema_version.split(".", 1)[0]
    ours = RESULTS_SCHEMA_VERSION.split(".", 1)[0]
    if theirs != ours:
        raise ResultsIntegrityError(
            f"results.json schema version {schema_version} is not supported by this "
            f"vip (understands {RESULTS_SCHEMA_VERSION}); upgrade vip or regenerate the results"
        )
```

Add the import of the results schema constant at the top of `traceability.py`:

```python
from vip.reporting import RESULTS_SCHEMA_VERSION, ReportData
```

- [ ] Step 4: Add the CLI subcommand

In `src/vip/cli.py`, add the handler near the other `run_*` functions:

```python
def run_trace(args: argparse.Namespace) -> None:
    """Join a results.json against a control list and emit a traceability matrix."""
    from vip.reporting import load_results
    from vip.traceability import (
        ControlListError,
        ResultsIntegrityError,
        build_traceability_matrix,
        check_results_schema,
        load_controls,
        render_csv,
        render_json,
        verify_results_checksum,
    )

    results_path = Path(args.results)
    if not results_path.is_file():
        print(f"Error: results file not found: {results_path}", file=sys.stderr)
        sys.exit(1)

    try:
        verify_results_checksum(results_path)
        data = load_results(results_path)
        check_results_schema(data.schema_version)
        controls = load_controls(args.controls)
    except (ResultsIntegrityError, ControlListError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    matrix = build_traceability_matrix(data, controls, tag_prefix=args.tag_prefix)

    if matrix.unrecognized_tags:
        joined = ", ".join(matrix.unrecognized_tags)
        print(
            f"Warning: control tags present in results but absent from the control list: {joined}",
            file=sys.stderr,
        )

    rendered = render_json(matrix) if args.format == "json" else render_csv(matrix)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        print(f"Wrote {out} ({len(matrix.entries)} controls, {matrix.gap_count} gaps)")
    else:
        sys.stdout.write(rendered)
```

Add the subparser after the `scaffold_parser.set_defaults(func=run_scaffold)` line:

```python
    trace_parser = subparsers.add_parser(
        "trace",
        help="Generate a compliance traceability matrix from test results",
        description=(
            "Join a results.json against a control list (controls.toml) and emit a "
            "control-to-scenario traceability matrix as CSV or JSON.\n\n"
            "Scenarios declare the control they satisfy with an @control-<slug> "
            "Gherkin tag. Controls with no matching scenario are reported as coverage "
            "gaps, except those marked verification = \"manual\" or \"procedural\", "
            "which are reported as not verifiable by automated test."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    trace_parser.add_argument(
        "--results",
        default="report/results.json",
        help="Path to results.json (default: report/results.json)",
    )
    trace_parser.add_argument(
        "--controls", required=True, help="Path to the controls.toml control list"
    )
    trace_parser.add_argument(
        "--tag-prefix",
        default="control-",
        help="Gherkin tag prefix identifying control tags (default: control-)",
    )
    trace_parser.add_argument(
        "--format", choices=("csv", "json"), default="csv", help="Output format (default: csv)"
    )
    trace_parser.add_argument(
        "--output", default=None, help="Write to this path instead of stdout"
    )
    trace_parser.set_defaults(func=run_trace)
```

Add `"trace": trace_parser,` to the `subcommand_parsers` dict.

- [ ] Step 5: Run test to verify it passes

Run: `uv run pytest selftests/test_trace_cli.py -v`
Expected: 10 passed

- [ ] Step 6: Check the help renders

Run: `uv run vip trace --help`
Expected: usage text listing all five options

- [ ] Step 7: Commit

```bash
git add src/vip/cli.py src/vip/traceability.py selftests/test_trace_cli.py
git commit -m "feat(cli): add vip trace for compliance traceability matrices"
```

---

### Task 11: `examples/part11_validation` scaffold template

Files:
- Create: `examples/part11_validation/README.md`, `test_part11_validation.feature`, `test_part11_validation.py`, `conftest.py`, `controls.toml`
- Modify: `src/vip/cli.py:1087-1096` (`_SCAFFOLD_TEMPLATES`), `src/vip/cli.py:1136-1138` (`_scaffold_next_steps`)
- Modify: `pyproject.toml:157-163` (`force-include`)
- Test: `selftests/test_part11_example.py` (create)

Interfaces:
- Consumes: the `@control-*` convention (Tasks 5-6), `vip trace` (Task 10)
- Produces: `vip scaffold --template part11-validation --output DIR`

Two things that are easy to miss. The wheel embeds scaffold sources via `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml` — without a new entry there, the template works from a source checkout and breaks from an installed wheel. And per CLAUDE.md every `@scenario` function needs a literal `@pytest.mark.connect` decorator: feature-level Gherkin tags alone do not drive auto-skip in extension directories.

Scope honesty requirement: the README must state that this is a template, not a certified Part 11 test set, and that a fully green matrix is evidence for the subset of controls a customer chose to automate — not a Part 11 compliance attestation. Posit Team does not implement electronic signatures, so 11.50, 11.70 and all of subpart C cannot be evidenced by a test against these products.

- [ ] Step 1: Write the failing test

Create `selftests/test_part11_example.py`:

```python
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "part11_validation"


def test_example_directory_exists():
    assert (EXAMPLE / "test_part11_validation.feature").is_file()
    assert (EXAMPLE / "test_part11_validation.py").is_file()
    assert (EXAMPLE / "controls.toml").is_file()
    assert (EXAMPLE / "README.md").is_file()


def test_template_is_registered():
    from vip.cli import _SCAFFOLD_TEMPLATES

    assert "part11-validation" in _SCAFFOLD_TEMPLATES
    assert _SCAFFOLD_TEMPLATES["part11-validation"][0] == "part11_validation"


def test_template_is_bundled_into_the_wheel():
    """A template missing from force-include works in-repo and breaks when installed."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    includes = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert includes["examples/part11_validation"] == "vip/_scaffold/part11_validation"


def test_every_control_tag_is_defined_in_controls_toml():
    feature = (EXAMPLE / "test_part11_validation.feature").read_text()
    tags = {
        tok.lstrip("@")
        for line in feature.splitlines()
        for tok in line.split()
        if tok.startswith("@control-")
    }
    controls = tomllib.loads((EXAMPLE / "controls.toml").read_text())["controls"]
    for tag in tags:
        assert tag.removeprefix("control-") in controls, f"{tag} missing from controls.toml"


def test_controls_toml_shows_the_not_automatable_path():
    """The worked example must demonstrate more than the happy path."""
    controls = tomllib.loads((EXAMPLE / "controls.toml").read_text())["controls"]
    verifications = {c.get("verification", "automated") for c in controls.values()}
    responsibilities = {c.get("responsibility") for c in controls.values()}
    assert verifications & {"manual", "procedural"}
    assert "customer" in responsibilities


def test_readme_states_it_is_not_an_attestation():
    text = (EXAMPLE / "README.md").read_text().lower()
    assert "not a certified" in text or "not an attestation" in text
    assert "electronic signature" in text


def test_scenarios_carry_literal_product_markers():
    """Feature-level Gherkin tags alone do not drive auto-skip in extensions."""
    steps = (EXAMPLE / "test_part11_validation.py").read_text()
    assert steps.count("@pytest.mark.connect") + steps.count("@pytest.mark.workbench") >= 3


def test_example_collects():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(EXAMPLE), "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] Step 2: Run test to verify it fails

Run: `uv run pytest selftests/test_part11_example.py -v`
Expected: FAIL on `test_example_directory_exists`

- [ ] Step 3: Create the example

`examples/part11_validation/controls.toml`:

```toml
# Sample control list for `vip trace`. This is a TEMPLATE: replace these
# entries with your organisation's own regulatory mapping. VIP does not
# interpret `reference`, `risk` or `responsibility` -- they are carried
# through to the matrix verbatim.

[controls.audit-trail-publish]
description = "Deployment of content is recorded with actor and timestamp"
reference = "21 CFR 11.10(e)"
risk = "high"
verification = "automated"
responsibility = "shared"
notes = "Retention duration of the audit log is a customer configuration decision."

[controls.access-control-privileged-action]
description = "Only authorised individuals may perform privileged actions"
reference = "21 CFR 11.10(g)"
risk = "high"
verification = "automated"
responsibility = "shared"

[controls.record-retention]
description = "Audit trail entries cannot be altered or deleted by ordinary users"
reference = "21 CFR 11.10(e)"
risk = "high"
verification = "automated"
responsibility = "shared"

[controls.personnel-training]
description = "Personnel have the education, training and experience to perform their tasks"
reference = "21 CFR 11.10(i)"
risk = "medium"
verification = "procedural"
responsibility = "customer"
notes = "Evidenced by training records in your QMS. No automated test can establish this."

[controls.signature-manifestation]
description = "Signed records display the signer's printed name, date/time and meaning"
reference = "21 CFR 11.50"
risk = "high"
verification = "manual"
responsibility = "customer"
notes = """
Posit Team does not implement electronic signatures. This control is satisfied
by the application you build on top of Posit Team, not by the platform, and is
listed here to show how a non-automatable control appears in the matrix.
"""
```

`examples/part11_validation/test_part11_validation.feature`:

```gherkin
@connect
Feature: Part 11 flavoured controls
  As a validation lead in a regulated environment
  I want automated evidence for the controls that can be automated
  So that my traceability matrix is generated rather than hand-maintained

  @control-audit-trail-publish
  Scenario: Publishing content is recorded with an actor and a timestamp
    Given Connect is accessible at the configured URL
    When I list recent audit log entries
    Then each entry records an actor and a timestamp

  @control-access-control-privileged-action
  Scenario: A privileged action requires authorisation
    Given Connect is accessible at the configured URL
    When I request a privileged administrative endpoint without credentials
    Then the request is refused

  @control-record-retention
  Scenario: Audit log entries cannot be deleted through the API
    Given Connect is accessible at the configured URL
    When I attempt to delete an audit log entry
    Then the deletion is refused
```

`examples/part11_validation/conftest.py`:

```python
"""Override points for the Part 11 example.

Redefine these fixtures in your own conftest.py to point the scenarios at the
endpoints your deployment exposes.
"""

import pytest


@pytest.fixture
def privileged_endpoint() -> str:
    """An administrative endpoint that must refuse an unauthenticated caller."""
    return "/__api__/v1/users"


@pytest.fixture
def audit_log_endpoint() -> str:
    """The audit log collection endpoint."""
    return "/__api__/v1/audit_logs"
```

`examples/part11_validation/test_part11_validation.py`:

```python
"""Step definitions for the Part 11 example.

Every @scenario function carries a literal @pytest.mark.connect decorator:
feature-level Gherkin tags alone do not drive VIP's auto-skip in extension
directories.
"""

import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.connect
@scenario("test_part11_validation.feature", "Publishing content is recorded with an actor and a timestamp")
def test_audit_trail_publish():
    pass


@pytest.mark.connect
@scenario("test_part11_validation.feature", "A privileged action requires authorisation")
def test_privileged_action_denied():
    pass


@pytest.mark.connect
@scenario("test_part11_validation.feature", "Audit log entries cannot be deleted through the API")
def test_audit_log_not_deletable():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    if connect_client is None:
        pytest.skip("Connect is not configured")
    return connect_client


@when("I list recent audit log entries", target_fixture="audit_entries")
def list_audit_entries(connect_client, audit_log_endpoint):
    response = connect_client.get(audit_log_endpoint)
    if response.status_code == 404:
        pytest.skip("this deployment does not expose an audit log endpoint")
    payload = response.json()
    return payload.get("results", payload) if isinstance(payload, dict) else payload


@then("each entry records an actor and a timestamp")
def entries_have_actor_and_timestamp(audit_entries):
    if not audit_entries:
        pytest.skip("no audit entries to inspect")
    for entry in audit_entries:
        assert entry.get("user_id") or entry.get("user_description"), (
            f"audit entry has no actor: {entry}"
        )
        assert entry.get("time") or entry.get("timestamp"), (
            f"audit entry has no timestamp: {entry}"
        )


@when("I request a privileged administrative endpoint without credentials",
      target_fixture="unauthenticated_response")
def request_privileged_endpoint(connect_client, privileged_endpoint):
    return connect_client.get_unauthenticated(privileged_endpoint)


@then("the request is refused")
def request_refused(unauthenticated_response):
    assert unauthenticated_response.status_code in (401, 403), (
        f"expected 401/403, got {unauthenticated_response.status_code}"
    )


@when("I attempt to delete an audit log entry", target_fixture="delete_response")
def delete_audit_entry(connect_client, audit_log_endpoint):
    return connect_client.delete(f"{audit_log_endpoint}/1")


@then("the deletion is refused")
def deletion_refused(delete_response):
    assert delete_response.status_code in (401, 403, 404, 405), (
        f"audit log deletion was not refused: {delete_response.status_code}"
    )
```

Note for the implementer: `connect_client.get_unauthenticated` and `.delete` may not exist on `src/vip/clients/connect.py`. This is the spec's stated open question. Check first; if either is missing, add it there following the existing method style (raw httpx, returns the response, no product SDK) as part of this task, with a selftest for the new client method. Do not inline httpx calls in the step file — that violates the four-layer architecture.

`examples/part11_validation/README.md`:

```markdown
# Part 11 validation example

A worked example of mapping regulatory controls to automated tests, and
exporting the result as a traceability matrix with `vip trace`.

## What this is not

This is a template, not a certified Part 11 test set. A fully green matrix is
evidence for the subset of controls you chose to automate. It is not an
attestation of 21 CFR Part 11 compliance, and nobody should present it as one.

Most of Part 11 cannot be evidenced by an automated test against Posit Team.
Roughly six clauses are genuinely testable against a deployment — 11.10(a),
11.10(d), 11.10(e), 11.10(g), 11.30, and partly 11.10(b). Several more are
shared with your own procedures. The rest are either procedural (11.10(i),
11.10(j)) or properties of the application you build on top of Posit Team.

In particular, Posit Team does not implement electronic signatures. Clause
11.50 (signature manifestations), 11.70 (signature/record linking) and all of
subpart C (11.100, 11.200, 11.300) are satisfied by your application and your
SOPs, not by Connect, Workbench or Package Manager. `controls.toml` includes
two such controls so you can see how a non-automatable control appears in the
matrix: as "not verifiable by automated test", which is deliberately distinct
from "coverage gap".

## How it works

A scenario declares the control it satisfies with a Gherkin tag:

```gherkin
@control-audit-trail-publish
Scenario: Publishing content is recorded with an actor and a timestamp
```

Write the product tag (`@connect`, `@workbench`) first — VIP derives the
feature's marker from the first non-control tag, and that value feeds the HTML
report and the generated test catalog.

`controls.toml` names each control and carries whatever metadata your
regulatory mapping uses. Only `description` is required.

## Running it

```bash
vip verify --config vip.toml --vip-extensions ./part11_validation
vip trace --results report/results.json --controls ./part11_validation/controls.toml
```

Add `--format json` for a machine-readable matrix carrying the full provenance
block, or `--output matrix.csv` to write to a file.

## Extending it

Replace `controls.toml` with your own mapping and tag your own scenarios. See
`security/test_auth_policy.py` in the VIP source for a fuller reference
implementation of access-control testing, and
`examples/cross_product_validation/` for the broader GxP starting point.
```

- [ ] Step 4: Register the template

In `src/vip/cli.py`, add to `_SCAFFOLD_TEMPLATES`:

```python
    "part11-validation": (
        "part11_validation",
        "Compliance control tagging plus a controls.toml for `vip trace`",
    ),
```

Add a branch to `_scaffold_next_steps`:

```python
    if template == "part11-validation":
        return (
            f"\nNext steps:\n"
            f"  1. Replace {dest / 'controls.toml'} with your own control list.\n"
            f"  2. Tag your scenarios with @control-<slug> matching those ids.\n"
            f"  3. Run: vip verify --vip-extensions {dest}\n"
            f"  4. Run: vip trace --controls {dest / 'controls.toml'}\n"
        )
```

In `pyproject.toml`, add to `[tool.hatch.build.targets.wheel.force-include]`:

```toml
"examples/part11_validation" = "vip/_scaffold/part11_validation"
```

- [ ] Step 5: Run test to verify it passes

Run: `uv run pytest selftests/test_part11_example.py -v`
Expected: 8 passed

- [ ] Step 6: Verify scaffolding end to end

```bash
uv run vip scaffold --list
uv run vip scaffold --template part11-validation --output /tmp/p11-check
uv run vip trace --results report/results.json --controls /tmp/p11-check/controls.toml || true
```
Expected: the template is listed, the directory is created with an `AGENTS.md`, and `vip trace` either produces a matrix or reports a missing results file cleanly.

- [ ] Step 7: Lint and commit

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
uv run ruff format src/ src/vip_tests/ selftests/ examples/
git add examples/part11_validation src/vip/cli.py pyproject.toml selftests/test_part11_example.py
git commit -m "feat(examples): add a part11 validation scaffold template"
```

---

### Task 12: Documentation

Files:
- Modify: `docs/reporting.md`, `docs/test-architecture.md`
- Modify: `CLAUDE.md` (key source files table)
- Test: `selftests/test_scaffold_agents_md.py` (verify, update only if it fails)

Interfaces:
- Consumes: everything above
- Produces: no code

`docs/reporting.md` currently mentions none of `results.json`, `junit.xml` or `results.sarif`. Document the machine-readable outputs first, then layer the traceability export on top — `vip trace --help` alone is not discovery.

- [ ] Step 1: Confirm the scaffold inventory test still passes

Run: `uv run pytest selftests/test_scaffold_agents_md.py -v`
Expected: pass. The new example reuses existing fixtures and markers, so no inventory update should be needed. If it fails, update `examples/_shared/AGENTS.md` to match the real inventory.

- [ ] Step 2: Document the machine-readable outputs in `docs/reporting.md`

Add a section covering: the three output formats and how `--vip-format` selects them; the `results.json` field inventory including `schema_version`, `started_at`/`finished_at`, and the `execution` block; the schema compatibility policy (unknown minor accepted, unknown major refused); the `.sha256` sidecar and how to verify it with `shasum -a 256 -c results.json.sha256`.

State the two honesty points in plain language, not just in the spec:
- `python_version`, `platform` and `execution.hostname` describe the VIP runner, not the system under test. The products table identifies the system under test.
- The checksum is tamper-evidence within a trusted pipeline, not tamper-proofing: anyone who can edit `results.json` can regenerate the sidecar. It catches corruption, truncated uploads and casual editing.

Then add a traceability section covering the `controls.toml` format, the three coverage outcomes, and a worked `vip trace` invocation.

- [ ] Step 3: Document the tagging convention in `docs/test-architecture.md`

Add a section covering the `@control-<slug>` convention, the rule that the product tag goes first (and why: `gherkin.py` derives the feature marker from the first non-control tag), that tags become registered pytest markers so `--strict-markers` runs work, and that they flow into `results.json` markers but not into SARIF or JUnit.

- [ ] Step 4: Update the key source files table in `CLAUDE.md`

Add rows for `src/vip/attribution.py` and `src/vip/traceability.py`, and extend the `src/vip/cli.py` row to mention `trace`.

- [ ] Step 5: Full verification

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
uv run pytest selftests/ -q
uv run vip verify --config vip.toml --collect-only 2>/dev/null || uv run pytest src/vip_tests/ --collect-only -q
```
Expected: lint clean, all selftests pass, product tests still collect.

- [ ] Step 6: Commit

```bash
git add docs/reporting.md docs/test-architecture.md CLAUDE.md
git commit -m "docs: document control tagging and the traceability export"
```

---

## Post-implementation cleanup

Per CLAUDE.md, at the end of the plan remove the plan and the spec:

```bash
git rm docs/superpowers/plans/2026-08-28-part11-traceability.md
git rm docs/superpowers/specs/2026-08-28-part11-traceability-design.md
git commit -m "chore: remove completed part11 traceability plan and spec"
```

Do this only after Task 12 is merged and verified.

## Deliberately not in this plan

Named so a later round does not rediscover them, and so nobody mistakes their
absence for an oversight. All are recorded in section 7.5 of the spec.

- Step-level Given/When/Then evidence. Real qualification protocols cite a
  protocol step; VIP captures nothing below the scenario. This is the largest
  remaining gap against how these documents are actually written.
- Captured stdout/log as evidence on a failure row.
- A deviation log, which needs cross-run history.
- Cryptographic signing of the evidence record.
- Runtime versions on the system under test in the provenance block.
- SARIF `properties.tags` carrying control tags.
- PDF rendering, owned by a separate team.
