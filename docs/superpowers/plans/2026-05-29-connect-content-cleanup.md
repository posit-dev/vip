# Reliable Connect Content Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every Connect content item VIP creates is deleted regardless of test outcome, via explicit GUID tracking, an autouse per-test finalizer, and a session-scoped end-of-run sweep.

**Architecture:** Move the delete logic into `ConnectClient` (tested with `httpx.MockTransport`) with an idempotent verify-and-retry delete. Connect test fixtures track created GUIDs in a session-scoped list; a function-scoped autouse finalizer deletes this test's content on pass or fail, and a session-scoped sweep cleans tracked GUIDs plus the `_vip_test` tag (cross-run).

**Tech Stack:** Python, httpx, pytest, pytest-bdd.

Spec: `docs/superpowers/specs/2026-05-29-connect-content-cleanup-design.md`

---

## File Structure

- `src/vip/clients/connect.py` — add `_delete_content_verified` + `cleanup_content`; rework `cleanup_vip_content` to use them. Core, reusable, tested.
- `src/vip_tests/connect/conftest.py` — add `_connect_created_guids` (session), `_connect_content_cleanup` (function, autouse), `_connect_end_of_run_sweep` (session, autouse).
- `src/vip_tests/connect/test_content_deploy.py` — append created GUID to the tracker in the create step.
- `src/vip_tests/connect/test_packages.py` — append created GUID to the tracker in the create step.
- `selftests/test_connect_cleanup.py` — new selftests via `httpx.MockTransport`.

---

## Task 1: Verified delete + `cleanup_content` on ConnectClient

**Files:**
- Modify: `src/vip/clients/connect.py`
- Test: `selftests/test_connect_cleanup.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `selftests/test_connect_cleanup.py`:

```python
"""Selftests for ConnectClient VIP-content cleanup helpers.

No real network connections are made: the ConnectClient's internal httpx
client is replaced with one backed by httpx.MockTransport.  The client's
base URL includes the ``/__api__`` prefix so request paths look like
``/__api__/v1/content/<guid>``.
"""

from __future__ import annotations

import httpx

from vip.clients.connect import ConnectClient


def _client_with_handler(handler) -> ConnectClient:
    """Build a ConnectClient whose httpx client uses a MockTransport."""
    cc = ConnectClient("https://connect.example.com", api_key="k")
    cc._client.close()
    cc._client = httpx.Client(
        base_url="https://connect.example.com/__api__",
        transport=httpx.MockTransport(handler),
    )
    return cc


def test_cleanup_content_deletes_and_verifies():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(404)  # verify: confirmed gone
        return httpx.Response(200)

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a", "b"]) == 2
    assert ("DELETE", "/__api__/v1/content/a") in calls
    assert ("DELETE", "/__api__/v1/content/b") in calls


def test_cleanup_content_idempotent_on_404_delete():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)  # DELETE 404 = already gone

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a"]) == 1


def test_cleanup_content_retries_until_gone():
    get_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        if request.method == "GET":
            get_calls["n"] += 1
            # Still present on first verify, gone on the second.
            return httpx.Response(200) if get_calls["n"] == 1 else httpx.Response(404)
        return httpx.Response(200)

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a"], settle_seconds=0) == 1
    assert get_calls["n"] == 2


def test_cleanup_content_skips_falsy_guids():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(404)

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["", None]) == 0
    assert calls == []  # no requests issued for falsy guids


def test_cleanup_content_returns_zero_and_does_not_raise_on_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a"], retries=2, settle_seconds=0) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_connect_cleanup.py -n0 -v`
Expected: FAIL with `AttributeError: 'ConnectClient' object has no attribute 'cleanup_content'`

- [ ] **Step 3: Write minimal implementation**

In `src/vip/clients/connect.py`, add these two methods to `ConnectClient` immediately after the existing `delete_content` method (which ends at the line `resp.raise_for_status()` around line 114). Use a local `import time` to match the existing style in `wait_for_task`:

```python
    def _delete_content_verified(
        self, guid: str, *, retries: int = 2, settle_seconds: float = 1.0
    ) -> bool:
        """Delete a content item and confirm it is gone.  Never raises.

        Treats a 404 (already gone) as success.  After deleting, GETs the item
        to confirm a 404 and retries up to *retries* times if it is still
        present.  Returns True once the content is confirmed gone.
        """
        import time

        for attempt in range(retries):
            try:
                resp = self._client.delete(f"/v1/content/{guid}")
                if resp.status_code == 404:
                    return True
            except Exception:
                pass
            try:
                check = self._client.get(f"/v1/content/{guid}")
                if check.status_code == 404:
                    return True
            except Exception:
                pass
            if attempt < retries - 1:
                time.sleep(settle_seconds)
        return False

    def cleanup_content(
        self, guids, *, retries: int = 2, settle_seconds: float = 1.0
    ) -> int:
        """Delete the given content GUIDs, verifying each is gone.  Never raises.

        Skips falsy GUIDs.  Returns the number of items confirmed deleted.
        """
        deleted = 0
        for guid in guids:
            if not guid:
                continue
            if self._delete_content_verified(
                guid, retries=retries, settle_seconds=settle_seconds
            ):
                deleted += 1
        return deleted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/test_connect_cleanup.py -n0 -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint + format**

Run: `uvx ruff@0.15.0 check src/ selftests/`
Run: `uvx ruff@0.15.0 format src/vip/clients/connect.py selftests/test_connect_cleanup.py`
Expected: `All checks passed!` and files formatted.

- [ ] **Step 6: Commit**

```bash
git add src/vip/clients/connect.py selftests/test_connect_cleanup.py
git commit -m "feat(connect): add verified, idempotent content cleanup helpers"
```

---

## Task 2: Harden `cleanup_vip_content` to use the verified delete

**Files:**
- Modify: `src/vip/clients/connect.py:202-217`
- Test: `selftests/test_connect_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Append to `selftests/test_connect_cleanup.py`:

```python
def test_cleanup_vip_content_lists_by_tag_then_deletes():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and path.endswith("/v1/tags"):
            return httpx.Response(200, json=[{"id": "t1", "name": "_vip_test"}])
        if request.method == "GET" and path.endswith("/v1/tags/t1/content"):
            return httpx.Response(200, json={"results": [{"guid": "a"}, {"guid": "b"}]})
        if request.method == "DELETE":
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(404)  # verify on /v1/content/<guid>
        return httpx.Response(200)

    cc = _client_with_handler(handler)
    assert cc.cleanup_vip_content() == 2
    # The hardened path verifies each delete with a follow-up GET; the old
    # single-shot delete_content loop never did, so this drives the change.
    assert ("GET", "/__api__/v1/content/a") in calls
    assert ("GET", "/__api__/v1/content/b") in calls


def test_cleanup_vip_content_no_raise_when_tag_lookup_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/tags"):
            return httpx.Response(500)
        return httpx.Response(200)

    cc = _client_with_handler(handler)
    assert cc.cleanup_vip_content() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/test_connect_cleanup.py -n0 -v -k cleanup_vip_content`
Expected: `test_cleanup_vip_content_lists_by_tag_then_deletes` FAILS — the current `cleanup_vip_content` calls the old `delete_content` (a single DELETE, no verify), so the asserted verify GET on `/__api__/v1/content/<guid>` is never issued. `test_cleanup_vip_content_no_raise_when_tag_lookup_fails` already passes (list returns `[]`).

- [ ] **Step 3: Write the implementation**

In `src/vip/clients/connect.py`, replace the entire existing `cleanup_vip_content` method (currently lines 202-217):

```python
    def cleanup_vip_content(self) -> int:
        """Delete all content tagged with the VIP test tag.

        Returns the number of items deleted.  Never raises.
        """
        guids = [item.get("guid") for item in self.list_vip_content()]
        return self.cleanup_content(guids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/test_connect_cleanup.py -n0 -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Lint + format**

Run: `uvx ruff@0.15.0 check src/ selftests/`
Run: `uvx ruff@0.15.0 format src/vip/clients/connect.py selftests/test_connect_cleanup.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/vip/clients/connect.py selftests/test_connect_cleanup.py
git commit -m "refactor(connect): route cleanup_vip_content through verified delete"
```

---

## Task 3: Connect cleanup fixtures

**Files:**
- Modify: `src/vip_tests/connect/conftest.py`

- [ ] **Step 1: Add the three fixtures**

In `src/vip_tests/connect/conftest.py`, append the following at the end of the file (after the `_make_tar_gz` helper). `pytest` is already imported at the top:

```python
# ---------------------------------------------------------------------------
# Content cleanup (issue #277 pattern): track created content and delete it
# regardless of test outcome, with a session-scoped end-of-run sweep.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _connect_created_guids():
    """Append-only record of content GUIDs created this run (tag-independent)."""
    return []


@pytest.fixture(autouse=True)
def _connect_content_cleanup(connect_client, _connect_created_guids):
    """Delete content created during this test, on pass or fail."""
    start = len(_connect_created_guids)
    yield
    if connect_client is None:
        return
    created = _connect_created_guids[start:]
    if created:
        connect_client.cleanup_content(created)


@pytest.fixture(scope="session", autouse=True)
def _connect_end_of_run_sweep(connect_client, _connect_created_guids):
    """End-of-run safety net: delete tracked GUIDs, then tag-based cross-run sweep."""
    yield
    if connect_client is None:
        return
    if _connect_created_guids:
        connect_client.cleanup_content(_connect_created_guids)
    connect_client.cleanup_vip_content()
```

- [ ] **Step 2: Verify it imports and collects**

Run: `uv run python -c "import vip_tests.connect.conftest"`
Expected: exits 0, no output.

Run: `uv run pytest src/vip_tests/connect/ --collect-only -q 2>&1 | tail -3`
Expected: collected (or "deselected" without config) with no collection errors.

- [ ] **Step 3: Lint + format**

Run: `uvx ruff@0.15.0 check src/`
Run: `uvx ruff@0.15.0 format src/vip_tests/connect/conftest.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/vip_tests/connect/conftest.py
git commit -m "fix(connect): add per-test cleanup finalizer and end-of-run sweep"
```

---

## Task 4: Track created GUIDs in the create steps

**Files:**
- Modify: `src/vip_tests/connect/test_content_deploy.py:342-356`
- Modify: `src/vip_tests/connect/test_packages.py:82-101`

- [ ] **Step 1: Track the GUID in the content-deploy create step**

In `src/vip_tests/connect/test_content_deploy.py`, the step at line 342 currently is:

```python
def create_content(connect_client, request):
    # Extract content name by matching the content type keyword (e.g., "plumber")
    # from the bundle name against the test function name (e.g., "test_deploy_plumber").
    test_name = request.node.name
    for name in _CONTENT_NAMES:
        # "vip-plumber-test" → "plumber", "vip-shiny-test" → "shiny", etc.
        content_type = name.split("-")[1]
        if content_type in test_name:
            content = connect_client.create_content(name)
            return {
                "guid": content["guid"],
                "name": name,
                "content_url": content.get("content_url", ""),
            }
    pytest.fail(f"No bundle configuration found matching test: {test_name}")
```

Replace it with (adds the `_connect_created_guids` fixture param and appends the GUID):

```python
def create_content(connect_client, request, _connect_created_guids):
    # Extract content name by matching the content type keyword (e.g., "plumber")
    # from the bundle name against the test function name (e.g., "test_deploy_plumber").
    test_name = request.node.name
    for name in _CONTENT_NAMES:
        # "vip-plumber-test" → "plumber", "vip-shiny-test" → "shiny", etc.
        content_type = name.split("-")[1]
        if content_type in test_name:
            content = connect_client.create_content(name)
            _connect_created_guids.append(content["guid"])
            return {
                "guid": content["guid"],
                "name": name,
                "content_url": content.get("content_url", ""),
            }
    pytest.fail(f"No bundle configuration found matching test: {test_name}")
```

- [ ] **Step 2: Track the GUID in the packages create step**

In `src/vip_tests/connect/test_packages.py`, the step at line 82 currently is:

```python
def deploy_r_content(connect_client):
    # Create content, upload the plumber bundle, and deploy.
    content = connect_client.create_content("vip-pm-repo-test")
    guid = content["guid"]
```

Replace those lines with (adds the fixture param and appends the GUID):

```python
def deploy_r_content(connect_client, _connect_created_guids):
    # Create content, upload the plumber bundle, and deploy.
    content = connect_client.create_content("vip-pm-repo-test")
    guid = content["guid"]
    _connect_created_guids.append(guid)
```

- [ ] **Step 3: Verify both modules collect**

Run: `uv run pytest src/vip_tests/connect/test_content_deploy.py src/vip_tests/connect/test_packages.py --collect-only -q 2>&1 | tail -3`
Expected: collected, no collection errors.

- [ ] **Step 4: Lint + format**

Run: `uvx ruff@0.15.0 check src/`
Run: `uvx ruff@0.15.0 format src/vip_tests/connect/test_content_deploy.py src/vip_tests/connect/test_packages.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/vip_tests/connect/test_content_deploy.py src/vip_tests/connect/test_packages.py
git commit -m "fix(connect): track created content GUIDs for reliable cleanup"
```

---

## Task 5: Full verification + showboat demo

**Files:**
- Create: `validation_docs/demo-connect-content-cleanup.md` (via `just demo-save`)

- [ ] **Step 1: Run the full selftest suite**

Run: `uv run pytest selftests/ -q 2>&1 | grep -E "passed|failed|error" | sed 's/ in [0-9.]*s//'`
Expected: all passed (no failures/errors).

- [ ] **Step 2: Lint + format checks (CI paths, pinned ruff)**

Run: `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`
Run: `uvx ruff@0.15.0 format --check src/ selftests/ examples/ docker/`
Expected: `All checks passed!` and all files already formatted.

- [ ] **Step 3: Build the showboat demo**

Use deterministic, timing-stripped commands (the suite runs under xdist; `-n0` forces single-process for stable ordering):

```bash
uvx showboat init demo.md "Fix: reliable Connect content cleanup"
uvx showboat note demo.md "Connect deploy tests previously left content on the server when a test failed before its cleanup step. Cleanup now lives in ConnectClient.cleanup_content() (idempotent verified delete with retry); created GUIDs are tracked and deleted by an autouse per-test finalizer plus a session-scoped end-of-run sweep that also runs the tag-based cross-run cleanup."
uvx showboat exec demo.md bash 'uv run pytest selftests/test_connect_cleanup.py -n0 -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"'
uvx showboat exec demo.md bash 'uvx ruff@0.15.0 check src/ selftests/ examples/ docker/'
uvx showboat exec demo.md bash 'uvx ruff@0.15.0 format --check src/ selftests/ examples/ docker/'
uvx showboat exec demo.md bash 'uv run pytest src/vip_tests/connect/ --collect-only -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"'
```

- [ ] **Step 4: Verify and archive the demo**

Run: `just demo-save connect-content-cleanup`
Expected: `showboat verify demo.md` passes; file moved to `validation_docs/demo-connect-content-cleanup.md`.

- [ ] **Step 5: Commit**

```bash
git add validation_docs/demo-connect-content-cleanup.md
git commit -m "test(connect): add content-cleanup demo"
```

---

## Task 6: Open the PR

- [ ] **Step 1: Remove the plan and spec (per repo convention)**

```bash
git rm docs/superpowers/plans/2026-05-29-connect-content-cleanup.md \
       docs/superpowers/specs/2026-05-29-connect-content-cleanup-design.md
git commit -m "chore: remove implementation plan and spec"
```

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin fix-connect-content-cleanup
gh pr create --title "fix(connect): reliably clean up VIP content on test failure" \
  --body-file <path to a body file you write, including a ## Demo section with the demo contents>
```

- [ ] **Step 3: Paste the demo under a `## Demo` heading** in the PR body (contents of `validation_docs/demo-connect-content-cleanup.md`).
