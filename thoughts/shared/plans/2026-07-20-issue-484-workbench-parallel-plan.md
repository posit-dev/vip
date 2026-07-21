# Workbench Test Parallelization Implementation Plan (#484)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the forced-serial Workbench test run (under shared OIDC auth) with parallel-by-group execution, made safe by a cross-worker OIDC login lock.

**Architecture:** Two changes in `src/vip_tests/workbench/conftest.py`, both gated on a shared auth session being active (`_auth_session_key`): (1) a **hybrid xdist grouping** — IDE-launch scenarios grouped by IDE, all other Workbench tests grouped by feature module — replacing the single `workbench_interactive_serial` pin; (2) a **cross-worker `filelock`** wrapping only the silent-SSO round-trip in `workbench_login`, so concurrent workers never storm the shared IdP session. Password / no-auth runs are untouched.

**Tech Stack:** Python 3.10+, pytest, pytest-bdd, pytest-xdist (LoadGroupScheduling), filelock, Playwright. Managed with `uv`.

## Global Constraints

- Run every command through `uv run` — never bare `python`/`pip`.
- Ruff is linter + formatter; line length 100; rules `E,F,I,UP`. `just check` must pass. CI pins ruff 0.15.0.
- All behavior changes activate **only** when `config.stash.get(_auth_session_key)` is not `None` (shared auth session present). Password / no-auth = today's default parallel behavior, unchanged.
- Single shared test account — no account pool.
- New pytest markers MUST be registered in `pyproject.toml` `[tool.pytest.ini_options] markers` or they raise warnings (CI cares about warnings).
- `filelock` goes in `[project].dependencies` (runtime), not a dev group — the `ci.yml` dependency audit checks runtime deps.
- xdist defaults are already `-n auto --dist loadgroup` (`pyproject.toml:162`) — no invocation change needed.
- Commits: per Ian's rules, use the `/commit` skill and get **explicit approval of every commit message** before running it. Commit steps below show the intended message; do not execute without approval.
- PR titles use conventional-commit format (`type: desc`, lowercase, <70 chars, no trailing period).
- Add a `showboat` demo before the PR (see CLAUDE.md); root `demo.md` is gitignored — archive via `just demo-save <name>`.

---

## File Structure

- `pyproject.toml` — add `filelock` runtime dep; register `rstudio`/`vscode`/`jupyter`/`positron` markers.
- `src/vip_tests/workbench/conftest.py` — add login-lock helpers + `_silent_sso_signin`; rewrite `pytest_collection_modifyitems` to hybrid grouping via a pure `_workbench_group_name` helper.
- `src/vip_tests/workbench/test_ide_launch.py` — decorate the four `@scenario` functions with IDE markers.
- `selftests/test_workbench_parallel.py` — new: unit tests for the lock helper, `_silent_sso_signin`, `_workbench_group_name`, and the collection hook's gate + assignment.

---

## Task 1: Cross-worker OIDC login lock helper

**Files:**
- Modify: `pyproject.toml` (`[project].dependencies`)
- Modify: `src/vip_tests/workbench/conftest.py` (imports + new helpers, after the `logger = ...` line ~32)
- Test: `selftests/test_workbench_parallel.py`

**Interfaces:**
- Produces: `_login_lock_path(workbench_url: str) -> Path`; `oidc_login_lock(workbench_url: str, *, timeout: float = _LOGIN_LOCK_TIMEOUT) -> ContextManager[None]` (a `@contextlib.contextmanager`). On lock-acquire timeout it logs a warning and yields anyway (never raises, never blocks the run).

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `[project].dependencies` (keep the list sorted-ish / grouped with the others):

```toml
    "filelock>=3.12",
```

- [ ] **Step 2: Sync and confirm it imports**

Run: `uv sync && uv run python -c "import filelock; print(filelock.__version__)"`
Expected: prints a version (e.g. `3.x.y`), no error.

- [ ] **Step 3: Write the failing test**

Create `selftests/test_workbench_parallel.py`:

```python
"""Selftests for #484 Workbench parallelization: login lock + hybrid grouping."""

from __future__ import annotations

import logging
from pathlib import Path

from filelock import FileLock

from vip_tests.workbench import conftest as wb


class TestOidcLoginLock:
    def test_lock_path_is_stable_and_url_scoped(self, tmp_path):
        a1 = wb._login_lock_path("https://wb.example.com")
        a2 = wb._login_lock_path("https://wb.example.com")
        b = wb._login_lock_path("https://other.example.com")
        assert a1 == a2  # stable for the same URL
        assert a1 != b  # distinct deployments get distinct locks
        assert a1.name.endswith(".lock")

    def test_lock_serializes_then_releases(self):
        url = "https://wb.example.com/serialize"
        with wb.oidc_login_lock(url):
            pass
        # Lock released: a fresh instance can acquire immediately.
        other = FileLock(str(wb._login_lock_path(url)))
        other.acquire(timeout=1)
        other.release()

    def test_lock_proceeds_on_timeout(self, caplog):
        url = "https://wb.example.com/contended"
        blocker = FileLock(str(wb._login_lock_path(url)))
        blocker.acquire()
        try:
            entered = False
            with caplog.at_level(logging.WARNING):
                with wb.oidc_login_lock(url, timeout=0.2):
                    entered = True
            assert entered  # proceeded despite not holding the lock
            assert "proceeding without it" in caplog.text
        finally:
            blocker.release()
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest selftests/test_workbench_parallel.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_login_lock_path'` (helpers not written yet).

- [ ] **Step 5: Implement the helpers**

In `src/vip_tests/workbench/conftest.py`, add to the imports block (top of file):

```python
import contextlib
import hashlib
import tempfile
```

and

```python
from filelock import FileLock, Timeout
```

Then, just after `logger = logging.getLogger(__name__)` (~line 32), add:

```python
# Cross-worker OIDC login lock (#484). Under --interactive-auth / --headless-auth every
# xdist worker shares one IdP session; letting many workers do the silent SSO round-trip
# simultaneously storms the IdP (the ?error=2 bounce from #467). Serializing just the
# round-trip removes the concurrency without re-serializing the whole suite.
_LOGIN_LOCK_TIMEOUT = float(os.environ.get("VIP_LOGIN_LOCK_TIMEOUT", "60"))


def _login_lock_path(workbench_url: str) -> Path:
    """Path to the cross-worker OIDC login lock for *workbench_url*.

    Keyed by a hash of the URL so distinct deployments don't share a lock, and placed in
    the system temp dir so all xdist workers on the host share the same file.
    """
    digest = hashlib.sha256(workbench_url.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"vip-wb-login-{digest}.lock"


@contextlib.contextmanager
def oidc_login_lock(workbench_url: str, *, timeout: float = _LOGIN_LOCK_TIMEOUT):
    """Serialize the OIDC SSO round-trip across xdist workers.

    Only one worker performs the silent SSO round-trip against the shared IdP session at a
    time. The lock is an optimization, never a correctness dependency: if it can't be
    acquired within *timeout*, log a warning and proceed unlocked rather than hang the run.
    """
    lock = FileLock(str(_login_lock_path(workbench_url)))
    try:
        lock.acquire(timeout=timeout)
    except Timeout:
        logger.warning(
            "OIDC login lock not acquired within %.0fs for %s; proceeding without it. "
            "Concurrent logins may briefly storm the IdP.",
            timeout,
            workbench_url,
        )
        yield
        return
    try:
        yield
    finally:
        lock.release()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest selftests/test_workbench_parallel.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Lint**

Run: `uv run ruff check src/ selftests/ && uv run ruff format --check src/ selftests/`
Expected: no errors.

- [ ] **Step 8: Commit** (via `/commit` skill, message approved by Ian)

Intended message: `feat(workbench): add cross-worker OIDC login lock`

---

## Task 2: Wire the login lock into the SSO round-trip

**Files:**
- Modify: `src/vip_tests/workbench/conftest.py` (`workbench_login`, the `interactive_auth and sso_only` branch ~lines 391-411)
- Test: `selftests/test_workbench_parallel.py`

**Interfaces:**
- Produces: `_silent_sso_signin(sso_button, homepage_logo, workbench_url: str) -> bool` — clicks the OIDC sign-in button and waits for the homepage, wrapped in `oidc_login_lock`. Returns `True` if the authenticated homepage appeared, `False` otherwise.
- Consumes: `oidc_login_lock` (Task 1), `TIMEOUT_PAGE_LOAD` (existing module constant).

- [ ] **Step 1: Write the failing test**

Append to `selftests/test_workbench_parallel.py`:

```python
class _FakeButton:
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class _FakeLogo:
    def __init__(self, *, appears: bool):
        self._appears = appears

    def wait_for(self, *, state, timeout):  # noqa: ARG002 - mirrors Playwright signature
        if not self._appears:
            raise RuntimeError("homepage never appeared")


class TestSilentSsoSignin:
    def test_returns_true_and_uses_lock_when_homepage_appears(self, monkeypatch):
        used = {"locked": False}

        import contextlib

        @contextlib.contextmanager
        def _spy_lock(url):
            used["locked"] = True
            used["url"] = url
            yield

        monkeypatch.setattr(wb, "oidc_login_lock", _spy_lock)
        button = _FakeButton()
        ok = wb._silent_sso_signin(button, _FakeLogo(appears=True), "https://wb.example.com")
        assert ok is True
        assert button.clicked is True
        assert used["locked"] is True
        assert used["url"] == "https://wb.example.com"

    def test_returns_false_when_homepage_never_appears(self, monkeypatch):
        import contextlib

        monkeypatch.setattr(wb, "oidc_login_lock", lambda url: contextlib.nullcontext())
        ok = wb._silent_sso_signin(_FakeButton(), _FakeLogo(appears=False), "https://wb.x")
        assert ok is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest selftests/test_workbench_parallel.py::TestSilentSsoSignin -v`
Expected: FAIL — `AttributeError: ... has no attribute '_silent_sso_signin'`.

- [ ] **Step 3: Add the helper**

In `conftest.py`, add above `workbench_login` (before the "Login Helper" section's `workbench_login` def):

```python
def _silent_sso_signin(sso_button, homepage_logo, workbench_url: str) -> bool:
    """Click the OIDC sign-in button and wait for the homepage, serialized across workers.

    Wrapped in :func:`oidc_login_lock` so concurrent xdist workers don't storm the shared
    IdP session. Returns ``True`` when the authenticated homepage appears, ``False``
    otherwise (the caller then skips with the standard message).
    """
    with oidc_login_lock(workbench_url):
        sso_button.click()
        try:
            homepage_logo.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Use the helper in `workbench_login`**

Replace the existing branch (current `conftest.py:391-411`):

```python
        if interactive_auth and sso_only:
            # Storage state was pre-loaded by --interactive-auth / --headless-auth.
            # Workbench's SSO sign-in page does not auto-redirect to the IdP; it
            # renders a "Sign in with OpenID" button.  Clicking it triggers a
            # silent SSO round-trip using the saved IdP cookies, landing on the
            # authenticated homepage with no credentials required.
            sso_button.click()
            try:
                homepage_logo.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
                return  # Silent SSO succeeded
            except Exception:
                # No usable IdP session (expired, or storage state was stripped
                # for the password-login test) — silent SSO can't complete on an
                # OIDC deployment, so skip gracefully.
                pytest.skip(
                    _workbench_session_skip_message(
                        auth_mode=auth_mode,
                        workbench_auth_error=workbench_auth_error,
                        landed_url=page.url,
                    )
                )
```

with:

```python
        if interactive_auth and sso_only:
            # Storage state was pre-loaded by --interactive-auth / --headless-auth.
            # Workbench's SSO sign-in page does not auto-redirect to the IdP; it renders a
            # "Sign in with OpenID" button. Clicking it triggers a silent SSO round-trip
            # using the saved IdP cookies. The round-trip is serialized across xdist
            # workers (see _silent_sso_signin / oidc_login_lock) to avoid storming the
            # shared IdP session (#484/#467).
            if _silent_sso_signin(sso_button, homepage_logo, workbench_url):
                return  # Silent SSO succeeded
            # No usable IdP session (expired, or storage state was stripped for the
            # password-login test) — skip gracefully.
            pytest.skip(
                _workbench_session_skip_message(
                    auth_mode=auth_mode,
                    workbench_auth_error=workbench_auth_error,
                    landed_url=page.url,
                )
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest selftests/test_workbench_parallel.py -v`
Expected: PASS (all classes).

- [ ] **Step 6: Regression — full selftests (excluding known-flaky timing file)**

Run: `uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q`
Expected: all pass (baseline was 1017 passed). `test_load_engine.py` is excluded per CLAUDE.md (timing-flaky, unrelated).

- [ ] **Step 7: Lint + commit** (via `/commit`, message approved)

Run: `uv run ruff check src/ selftests/ && uv run ruff format --check src/ selftests/`
Intended message: `feat(workbench): serialize OIDC sign-in via the login lock`

---

## Task 3: Mark IDE-launch scenarios by IDE

**Files:**
- Modify: `pyproject.toml` (register markers)
- Modify: `src/vip_tests/workbench/test_ide_launch.py` (decorate the four `@scenario` functions)
- Test: covered by Task 4's collection test (markers must exist for grouping to key on them)

**Interfaces:**
- Produces: pytest markers `rstudio`, `vscode`, `jupyter`, `positron` on the four IDE-launch test functions.

- [ ] **Step 1: Register the markers**

In `pyproject.toml` `[tool.pytest.ini_options] markers = [ ... ]`, add:

```toml
    "rstudio: Workbench RStudio IDE-launch scenario",
    "vscode: Workbench VS Code IDE-launch scenario",
    "jupyter: Workbench JupyterLab IDE-launch scenario",
    "positron: Workbench Positron IDE-launch scenario",
```

- [ ] **Step 2: Decorate the scenario functions**

In `src/vip_tests/workbench/test_ide_launch.py`, add one marker per `@scenario` function (markers are explicit decorators here rather than feature-file tags — matches the repo pattern of marking `@scenario` functions directly, and keeps the grouping signal in code the conftest reads):

```python
@pytest.mark.rstudio
@scenario("test_ide_launch.feature", "RStudio IDE session can be launched")
def test_launch_rstudio():
    pass


@pytest.mark.vscode
@scenario("test_ide_launch.feature", "VS Code session can be launched")
def test_launch_vscode():
    pass


@pytest.mark.jupyter
@scenario("test_ide_launch.feature", "JupyterLab session can be launched")
def test_launch_jupyter():
    pass


@pytest.mark.positron
@scenario("test_ide_launch.feature", "Positron session can be launched")
def test_launch_positron():
    pass
```

- [ ] **Step 3: Verify markers are attached with no warnings**

Run: `uv run pytest src/vip_tests/workbench/test_ide_launch.py --collect-only -q -m rstudio 2>&1 | grep -iE "warning|test_launch_rstudio"`
Expected: `test_launch_rstudio` collected; **no** "Unknown pytest.mark" warning.

- [ ] **Step 4: Lint + commit** (via `/commit`, message approved)

Intended message: `test(workbench): mark IDE-launch scenarios by IDE`

---

## Task 4: Hybrid xdist grouping in the workbench conftest

**Files:**
- Modify: `src/vip_tests/workbench/conftest.py` (`pytest_collection_modifyitems` ~lines 37-64 + new pure helper)
- Test: `selftests/test_workbench_parallel.py`

**Interfaces:**
- Produces: `_IDE_MARKERS: tuple[str, ...]`; `_workbench_group_name(ide_markers: set[str], module_stem: str) -> str`.
- Consumes: `_auth_session_key` (already imported at conftest top via `from vip.plugin import _auth_session_key`? — NOTE: it is referenced as `_auth_session_key` in the current hook, so it is already importable in this module).

- [ ] **Step 1: Write the failing tests**

Append to `selftests/test_workbench_parallel.py`:

```python
class TestWorkbenchGroupName:
    def test_ide_marker_wins(self):
        assert wb._workbench_group_name({"rstudio"}, "test_ide_launch") == "workbench_ide_rstudio"
        assert wb._workbench_group_name({"positron"}, "test_ide_launch") == "workbench_ide_positron"

    def test_non_ide_groups_by_module_stripping_test_prefix(self):
        assert wb._workbench_group_name(set(), "test_packages") == "workbench_packages"
        assert wb._workbench_group_name(set(), "test_git_ops") == "workbench_git_ops"

    def test_module_without_test_prefix_kept_verbatim(self):
        assert wb._workbench_group_name(set(), "chronicle_probe") == "workbench_chronicle_probe"


class _FakeMarker:
    def __init__(self, name):
        self.name = name


class _FakeItem:
    def __init__(self, path: Path, marker_names):
        self.path = path
        self.own_markers = [_FakeMarker("xdist_group"), _FakeMarker("workbench")]
        self._markers = [_FakeMarker(n) for n in marker_names]
        self.added = []

    def iter_markers(self):
        return list(self._markers)

    def add_marker(self, marker):
        # pytest.mark.xdist_group("g") -> mark object with .name and .args
        self.added.append((marker.name, marker.args))


class _FakeConfig:
    def __init__(self, session):
        self._session = session

    @property
    def stash(self):
        cfg = self

        class _Stash:
            def get(self, key, default=None):  # noqa: ARG002
                return cfg._session

        return _Stash()


class TestCollectionHook:
    def _wb_dir(self):
        return Path(wb.__file__).parent

    def test_no_auth_session_is_a_noop(self):
        item = _FakeItem(self._wb_dir() / "test_packages.py", [])
        wb.pytest_collection_modifyitems(_FakeConfig(None), [item])
        assert item.added == []  # untouched under password / no-auth

    def test_ide_item_grouped_by_ide(self):
        item = _FakeItem(self._wb_dir() / "test_ide_launch.py", ["workbench", "rstudio"])
        wb.pytest_collection_modifyitems(_FakeConfig(object()), [item])
        assert ("xdist_group", ("workbench_ide_rstudio",)) in item.added
        assert all(m.name != "xdist_group" for m in item.own_markers)  # old group stripped

    def test_non_ide_item_grouped_by_module(self):
        item = _FakeItem(self._wb_dir() / "test_packages.py", ["workbench"])
        wb.pytest_collection_modifyitems(_FakeConfig(object()), [item])
        assert ("xdist_group", ("workbench_packages",)) in item.added

    def test_non_workbench_item_ignored(self):
        item = _FakeItem(Path("/somewhere/connect/test_auth.py"), ["connect"])
        wb.pytest_collection_modifyitems(_FakeConfig(object()), [item])
        assert item.added == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest selftests/test_workbench_parallel.py::TestWorkbenchGroupName selftests/test_workbench_parallel.py::TestCollectionHook -v`
Expected: FAIL — `_workbench_group_name` missing / hook still assigns `workbench_interactive_serial`.

- [ ] **Step 3: Add the pure helper**

In `conftest.py`, just above `pytest_collection_modifyitems`:

```python
_IDE_MARKERS = ("rstudio", "vscode", "jupyter", "positron")


def _workbench_group_name(ide_markers: set[str], module_stem: str) -> str:
    """Compute the xdist group for a Workbench test under shared auth (hybrid grouping).

    IDE-launch scenarios (carrying an IDE marker) group by IDE so each IDE runs on its own
    worker: ``workbench_ide_<ide>``. Every other Workbench test groups by feature module:
    ``workbench_<stem>`` (a leading ``test_`` stripped).
    """
    for ide in _IDE_MARKERS:
        if ide in ide_markers:
            return f"workbench_ide_{ide}"
    stem = module_stem[len("test_"):] if module_stem.startswith("test_") else module_stem
    return f"workbench_{stem}"
```

- [ ] **Step 4: Rewrite the hook**

Replace the current `pytest_collection_modifyitems` body (`conftest.py:37-64`) with:

```python
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Group Workbench tests for parallel execution when a shared auth session is active.

    Under --interactive-auth / --headless-auth all Workbench tests authenticate as the same
    shared account. Rather than pin them all to one worker (the old serial workaround), we
    group them so LoadGroupScheduling spreads them across workers: IDE-launch scenarios by
    IDE (``workbench_ide_<ide>``), everything else by feature module (``workbench_<module>``).
    The simultaneous-login storm this used to cause is prevented by the cross-worker login
    lock in :func:`workbench_login` (see :func:`oidc_login_lock`), not by serialization.

    For password auth (no shared session) the default parallel behavior is preserved.
    """
    if config.stash.get(_auth_session_key, None) is None:
        # No shared auth session — password auth or no auth. Keep default parallel behavior.
        return

    workbench_dir = Path(__file__).parent
    for item in items:
        item_path = getattr(item, "path", None)
        if item_path is None or not item_path.is_relative_to(workbench_dir):
            continue
        ide_markers = {m.name for m in item.iter_markers()} & set(_IDE_MARKERS)
        group = _workbench_group_name(ide_markers, item_path.stem)
        # Replace the default xdist_group("workbench") from pytestmark with the hybrid group.
        item.own_markers = [m for m in item.own_markers if m.name != "xdist_group"]
        item.add_marker(pytest.mark.xdist_group(group))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest selftests/test_workbench_parallel.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Confirm collection still succeeds end-to-end**

Run: `uv run pytest src/vip_tests/workbench/ --collect-only -q 2>&1 | tail -5`
Expected: scenarios collected, no errors, no unknown-marker warnings.

- [ ] **Step 7: Full selftests + lint**

Run: `uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q && uv run ruff check src/ selftests/ && uv run ruff format --check src/ selftests/`
Expected: all pass, no lint errors.

- [ ] **Step 8: Commit** (via `/commit`, message approved)

Intended message: `feat(workbench): group tests by IDE/module instead of forcing serial`

---

## Task 5: Live validation gate (go / no-go) — required before merge

This is the acceptance gate the design calls for: the CI-testable parts above cannot prove that a *single shared account* sustains concurrent Workbench sessions or that the lock kills the `?error=2` storm. This must be run against a **live OIDC Workbench 2026.06** deployment.

**Files:** none (manual run + `showboat` demo capture).

- [ ] **Step 1: Configure a live run**

Point `vip.toml` (or `vip verify --workbench-url ...`) at a real OIDC Workbench 2026.06 deployment with the shared test account (`VIP_TEST_USERNAME` / `VIP_TEST_PASSWORD` / optional `VIP_TEST_TOTP_SECRET`).

- [ ] **Step 2: Run the Workbench suite in parallel under headless auth**

Run: `uv run vip verify --config vip.toml --categories workbench --headless-auth -- -v`
(xdist defaults `-n auto --dist loadgroup` apply.)

- [ ] **Step 3: Confirm the four acceptance criteria**

- Tests are distributed across **multiple** xdist workers (multiple `gw` ids in output), not pinned to one.
- **No** `?error=2` / sign-in-page bounces; no logins fail from contention.
- All Workbench tests that passed under the old serial run still pass.
- Wall-clock is **materially below** the ~10-minute serial baseline.

- [ ] **Step 4: If it fails — fall back, don't force it**

Options, in order: raise `VIP_LOGIN_LOCK_TIMEOUT`; cap concurrency (document running Workbench with fewer workers); if the storm persists even with serialized logins, the single-account premise is wrong → revisit the deferred "bake an established Workbench session into storage_state" option (design doc, "Out (deferred)").

- [ ] **Step 5: Capture a `showboat` demo and open a draft PR**

Build a demo proving the selftests pass and the live run parallelizes; `just demo-save workbench-parallel-484`; open a **draft** PR titled `test(workbench): parallelize tests by IDE type instead of forcing serial` (matches issue #484), linking `Closes #484`, with the demo under `## Demo`.

---

## Self-Review

**Spec coverage:**
- Hybrid grouping (IDE-launch by IDE, rest by module) → Tasks 3 + 4. ✓
- Gate on shared auth session only → Task 4 hook + `TestCollectionHook.test_no_auth_session_is_a_noop`. ✓
- Cross-worker login lock around the SSO round-trip only → Tasks 1 + 2. ✓
- Proceed-on-timeout (lock is optimization, not correctness) → Task 1 `test_lock_proceeds_on_timeout`. ✓
- `filelock` added to runtime deps → Task 1 Step 1. ✓
- Single shared account / no pool → honored (no account config added). ✓
- Live spike as the go/no-go gate with fallback → Task 5. ✓ (Sequenced last, since the lock/grouping code must exist to validate it; merge is blocked on it, satisfying "don't trust the rollout until proven.")

**Placeholder scan:** none — every code step shows complete code; every run step shows the command and expected result.

**Type consistency:** `oidc_login_lock` / `_login_lock_path` / `_silent_sso_signin` / `_workbench_group_name` / `_IDE_MARKERS` names are used identically across Tasks 1-4. `_silent_sso_signin(sso_button, homepage_logo, workbench_url)` signature matches its call site in Task 2 Step 4. ✓
