# Fix: workbench test_auth skip message for --headless-auth

*2026-04-17T20:59:42Z by Showboat 0.6.1*
<!-- showboat-id: 156fd57d-5612-4eba-b4b9-0b31b5f44e7d -->

Fixes issue #185: `test_workbench_login` was being skipped with a misleading message when run with `--headless-auth`. The skip reason said 'not compatible with --interactive-auth' even though `--interactive-auth` was not used.

Root cause: the `interactive_auth` fixture returned `True` whenever a pre-test auth session existed in the stash — true for both `--interactive-auth` and `--headless-auth` — and the workbench test blindly reported `--interactive-auth` in its skip message.

Fix: added a new `auth_mode` fixture that returns `"interactive"`, `"headless"`, or `"none"` so tests can distinguish the mode. The workbench test_auth.py now uses this fixture to produce an accurate skip message. Related skip messages in connect/test_auth.py and workbench/conftest.py were also updated to mention both modes.

## Plugin wiring: new `_auth_mode_key` stash

The plugin now stashes the auth mode in `pytest_configure` when either `--interactive-auth` or `--headless-auth` is used. For xdist, the mode is forwarded to workers via `workerinput` and restored in `_restore_worker_auth`.

```bash
git diff src/vip/plugin.py
```

```output
diff --git a/src/vip/plugin.py b/src/vip/plugin.py
index f611fd6..af58c48 100644
--- a/src/vip/plugin.py
+++ b/src/vip/plugin.py
@@ -40,6 +40,7 @@ _vip_config_key = pytest.StashKey[VIPConfig]()
 _ext_dirs_key = pytest.StashKey[list[str]]()
 _results_key = pytest.StashKey[list[dict[str, Any]]]()
 _auth_session_key = pytest.StashKey[Any]()
+_auth_mode_key = pytest.StashKey[str]()
 
 # Module-level reference to the active pytest.Config, set in pytest_configure.
 # Safe because pytester runs in a subprocess (fresh import each time).
@@ -167,6 +168,7 @@ def pytest_configure(config: pytest.Config) -> None:
         # xdist worker — restore auth data shared by the controller.
         _restore_worker_auth(config, vip_cfg)
     elif config.getoption("--interactive-auth"):
+        config.stash[_auth_mode_key] = "interactive"
         connect_url = vip_cfg.connect.url if vip_cfg.connect.is_configured else None
         wb_url = vip_cfg.workbench.url if vip_cfg.workbench.is_configured else None
 
@@ -193,6 +195,7 @@ def pytest_configure(config: pytest.Config) -> None:
                 stacklevel=1,
             )
     elif config.getoption("--headless-auth"):
+        config.stash[_auth_mode_key] = "headless"
         connect_url = vip_cfg.connect.url if vip_cfg.connect.is_configured else None
         wb_url = vip_cfg.workbench.url if vip_cfg.workbench.is_configured else None
 
@@ -249,6 +252,9 @@ def _restore_worker_auth(config: pytest.Config, vip_cfg: VIPConfig) -> None:
         _tmpdir="",  # Workers don't own the temp dir; controller cleans up.
     )
     config.stash[_auth_session_key] = session
+    mode = wi.get("vip_auth_mode")
+    if mode:
+        config.stash[_auth_mode_key] = mode
 
 
 def pytest_configure_node(node) -> None:
@@ -260,6 +266,7 @@ def pytest_configure_node(node) -> None:
         node.workerinput["vip_storage_state"] = str(auth.storage_state_path)
         node.workerinput["vip_key_name"] = auth.key_name
         node.workerinput["vip_connect_url"] = auth._connect_url
+        node.workerinput["vip_auth_mode"] = node.config.stash.get(_auth_mode_key, "")
 
 
 def pytest_sessionstart(session: pytest.Session) -> None:
```

## New `auth_mode` fixture

Added a session-scoped fixture in `src/vip_tests/conftest.py` that exposes the mode. The existing `interactive_auth` fixture keeps its "any session exists" semantics; callers that need to distinguish modes now use `auth_mode`.

```bash
git diff src/vip_tests/conftest.py
```

```output
diff --git a/src/vip_tests/conftest.py b/src/vip_tests/conftest.py
index 65a7035..13a8f22 100644
--- a/src/vip_tests/conftest.py
+++ b/src/vip_tests/conftest.py
@@ -9,7 +9,7 @@ from vip.clients.connect import ConnectClient
 from vip.clients.packagemanager import PackageManagerClient
 from vip.clients.workbench import WorkbenchClient
 from vip.config import PerformanceConfig, VIPConfig
-from vip.plugin import _auth_session_key, _vip_config_key
+from vip.plugin import _auth_mode_key, _auth_session_key, _vip_config_key
 
 # pytest-bdd step definitions with target_fixture return values intentionally;
 # pytest 9.x warns about non-None returns from test functions. Scoped to
@@ -89,11 +89,21 @@ def pm_url(vip_config: VIPConfig) -> str:
 
 @pytest.fixture(scope="session")
 def interactive_auth(request: pytest.FixtureRequest) -> bool:
-    """Whether interactive auth was used for this session."""
+    """Whether any pre-test auth flow established a browser session.
+
+    Returns True for both ``--interactive-auth`` and ``--headless-auth``; use
+    the ``auth_mode`` fixture to distinguish which mode is active.
+    """
     session = request.config.stash.get(_auth_session_key, None)
     return session is not None
 
 
+@pytest.fixture(scope="session")
+def auth_mode(request: pytest.FixtureRequest) -> str:
+    """The active auth mode: ``"interactive"``, ``"headless"``, or ``"none"``."""
+    return request.config.stash.get(_auth_mode_key, "none")
+
+
 @pytest.fixture(scope="session")
 def browser_context_args(browser_context_args, request: pytest.FixtureRequest):
     """Inject interactive auth storage state into all browser contexts.
```

## The fix: accurate skip message

The Workbench `test_auth.py` now checks `auth_mode` directly and produces a message that matches the actual CLI flag.

```bash
git diff src/vip_tests/workbench/test_auth.py
```

```output
diff --git a/src/vip_tests/workbench/test_auth.py b/src/vip_tests/workbench/test_auth.py
index 7ce82e6..008946a 100644
--- a/src/vip_tests/workbench/test_auth.py
+++ b/src/vip_tests/workbench/test_auth.py
@@ -20,12 +20,12 @@ def test_workbench_login():
 
 
 @given("Workbench is accessible at the configured URL")
-def workbench_accessible(workbench_client, auth_provider: str, interactive_auth: bool):
+def workbench_accessible(workbench_client, auth_provider: str, auth_mode: str):
     # This test only validates password-based login form flow
     if auth_provider != "password":
         pytest.skip(f"test_auth only supports password auth, not {auth_provider!r}")
-    if interactive_auth:
-        pytest.skip("test_auth is not compatible with --interactive-auth")
+    if auth_mode != "none":
+        pytest.skip(f"test_auth is not compatible with --{auth_mode}-auth")
 
     assert workbench_client is not None, "Workbench client not configured"
     status = workbench_client.health()
```

## Selftests

Added three new selftests that verify the plugin stashes the right mode based on CLI options. They mock the real browser auth via a conftest-level monkey-patch so they run without a real browser or Posit product.

```bash
uv run pytest selftests/test_plugin.py::TestAuthModeStash -v
```

```output
============================= test session starts ==============================
platform darwin -- Python 3.14.0, pytest-9.0.3, pluggy-1.6.0 -- /Users/briandeitte/vip/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/briandeitte/vip
configfile: pyproject.toml
plugins: anyio-4.12.1, playwright-0.7.2, shiny-1.5.1, posit-vip-0.24.1, cov-7.1.0, locust-2.43.4, xdist-3.8.0, base-url-2.1.0, bdd-8.1.0
collecting ... collected 3 items

selftests/test_plugin.py::TestAuthModeStash::test_no_auth_option_leaves_mode_none PASSED [ 33%]
selftests/test_plugin.py::TestAuthModeStash::test_interactive_auth_sets_mode PASSED [ 66%]
selftests/test_plugin.py::TestAuthModeStash::test_headless_auth_sets_mode PASSED [100%]

============================== 3 passed in 0.10s ===============================
```

## Full selftest suite still passes (246 tests)

```bash
uv run pytest selftests/ 2>&1 | grep -oE '^=+ [0-9]+ passed.*[0-9]+ warnings' | sed 's/ in [0-9.]*s//'
```

```output
======================= 246 passed, 4 warnings
```

## Lint and format checks pass

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
99 files already formatted
```
