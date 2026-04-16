"""VIP pytest plugin.

Registered via the ``pytest11`` entry point so it activates automatically
when the ``vip`` package is installed.

Responsibilities:
- Register custom markers.
- Add CLI options (``--vip-config``, ``--vip-extensions``, ``--vip-report``,
  ``--interactive-auth``).
- Deselect (exclude) tests whose product is not configured.
- Auto-skip tests whose product version doesn't meet ``min_version``.
- Ensure prerequisites run before other tests.
- Collect extension directories.
- Write a JSON results file for the Quarto report.
- Handle interactive OIDC authentication for external identity providers.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from vip.config import VIPConfig, load_config

# ---------------------------------------------------------------------------
# Stash keys
# ---------------------------------------------------------------------------

_vip_config_key = pytest.StashKey[VIPConfig]()
_ext_dirs_key = pytest.StashKey[list[str]]()
_results_key = pytest.StashKey[list[dict[str, Any]]]()
_auth_session_key = pytest.StashKey[Any]()

# Module-level reference to the active pytest.Config, set in pytest_configure.
# Safe because pytester runs in a subprocess (fresh import each time).
_active_config: pytest.Config | None = None

# Mapping from pytest marker name to product config key.
_PRODUCT_MARKERS = {
    "connect": "connect",
    "workbench": "workbench",
    "package_manager": "package_manager",
}

# ---------------------------------------------------------------------------
# Plugin hooks
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("vip", "Verified Installation of Posit")
    group.addoption(
        "--vip-config",
        default=None,
        help="Path to vip.toml configuration file.",
    )
    group.addoption(
        "--vip-extensions",
        action="append",
        default=[],
        help="Additional directories containing custom VIP test cases (repeatable).",
    )
    group.addoption(
        "--vip-report",
        default="report/results.json",
        help="Write a JSON results file at this path for Quarto report generation."
        " Set to empty string to disable. (default: report/results.json)",
    )
    group.addoption(
        "--interactive-auth",
        action="store_true",
        default=False,
        help="Launch a browser for manual OIDC login before running tests.",
    )
    group.addoption(
        "--headless-auth",
        action="store_true",
        default=False,
        help="Automate OIDC login in a headless browser (requires [auth] idp in config).",
    )
    group.addoption(
        "--no-auth",
        action="store_true",
        default=False,
        help="Skip all tests that require authentication credentials (Connect and Workbench).",
    )
    group.addoption(
        "--vip-verbose",
        action="store_true",
        default=False,
        help="Show full pytest tracebacks instead of concise error messages.",
    )


def pytest_configure(config: pytest.Config) -> None:
    global _active_config
    _active_config = config

    # Register markers
    config.addinivalue_line("markers", "connect: tests for Posit Connect")
    config.addinivalue_line("markers", "workbench: tests for Posit Workbench")
    config.addinivalue_line("markers", "package_manager: tests for Posit Package Manager")
    config.addinivalue_line("markers", "prerequisites: prerequisite checks")
    config.addinivalue_line("markers", "cross_product: cross-product / admin tests")
    config.addinivalue_line("markers", "performance: performance validation tests")
    config.addinivalue_line("markers", "security: security validation tests")
    config.addinivalue_line(
        "markers",
        "min_version(product, version): skip when product is below the specified version",
    )
    config.addinivalue_line(
        "markers",
        "if_applicable: skip when the related feature is not configured",
    )

    # In concise mode, suppress the "short test summary info" section — the
    # inline concise error messages make it redundant.
    if not config.getoption("--vip-verbose", default=False):
        config.option.reportchars = ""

    # Load VIP config and stash it for fixtures / collection hooks.
    vip_cfg = load_config(config.getoption("--vip-config"))
    config.stash[_vip_config_key] = vip_cfg

    # Initialize per-session results list (avoids module-level global).
    config.stash[_results_key] = []

    # Merge extension dirs from config file and CLI.
    ext_dirs: list[str] = list(vip_cfg.extension_dirs)
    ext_dirs.extend(config.getoption("--vip-extensions") or [])
    config.stash[_ext_dirs_key] = ext_dirs

    # Handle interactive auth — login via browser, then close before tests.
    # With pytest-xdist the browser auth happens once in the controller;
    # credentials are forwarded to workers via pytest_configure_node.
    config.stash[_auth_session_key] = None

    if hasattr(config, "workerinput") and config.workerinput.get("vip_interactive_auth"):
        # xdist worker — restore auth data shared by the controller.
        _restore_worker_auth(config, vip_cfg)
    elif config.getoption("--interactive-auth"):
        connect_url = vip_cfg.connect.url if vip_cfg.connect.is_configured else None
        wb_url = vip_cfg.workbench.url if vip_cfg.workbench.is_configured else None

        if not connect_url and not wb_url:
            raise pytest.UsageError(
                "--interactive-auth requires at least one product URL (Connect or Workbench)"
            )

        from pathlib import Path

        from vip.auth import start_interactive_auth

        cache_path = Path(config.rootpath) / ".vip-auth-cache.json"
        session = start_interactive_auth(
            connect_url=connect_url, workbench_url=wb_url, cache_path=cache_path
        )
        config.stash[_auth_session_key] = session
        if session.api_key:
            vip_cfg.connect.api_key = session.api_key
        elif connect_url:
            warnings.warn(
                "VIP: --interactive-auth could not mint an API key. "
                "API-based tests will likely fail. Set VIP_CONNECT_API_KEY to fix.",
                stacklevel=1,
            )
    elif config.getoption("--headless-auth"):
        connect_url = vip_cfg.connect.url if vip_cfg.connect.is_configured else None
        wb_url = vip_cfg.workbench.url if vip_cfg.workbench.is_configured else None

        if not connect_url and not wb_url:
            raise pytest.UsageError(
                "--headless-auth requires at least one product URL (Connect or Workbench)"
            )
        if not vip_cfg.auth.idp:
            raise pytest.UsageError(
                '--headless-auth requires [auth] idp in vip.toml (supported: "keycloak", "okta")'
            )

        from pathlib import Path

        from vip.auth import AuthConfigError, start_headless_auth

        cache_path = Path(config.rootpath) / ".vip-auth-cache.json"
        try:
            session = start_headless_auth(
                connect_url=connect_url,
                workbench_url=wb_url,
                idp=vip_cfg.auth.idp,
                username=vip_cfg.auth.username,
                password=vip_cfg.auth.password,
                cache_path=cache_path,
            )
        except AuthConfigError as exc:
            raise pytest.UsageError(str(exc)) from None
        config.stash[_auth_session_key] = session
        if session.api_key:
            vip_cfg.connect.api_key = session.api_key
        elif connect_url:
            warnings.warn(
                "VIP: --headless-auth could not mint an API key. "
                "API-based tests will likely fail. Set VIP_CONNECT_API_KEY to fix.",
                stacklevel=1,
            )


def _restore_worker_auth(config: pytest.Config, vip_cfg: VIPConfig) -> None:
    """Reconstruct an auth session in an xdist worker from controller data."""
    from vip.auth import InteractiveAuthSession

    wi = config.workerinput  # type: ignore[attr-defined]  # xdist injects this
    api_key = wi.get("vip_api_key") or None
    storage_state = wi.get("vip_storage_state", "")

    if api_key:
        vip_cfg.connect.api_key = api_key

    session = InteractiveAuthSession(
        storage_state_path=Path(storage_state) if storage_state else Path("/dev/null"),
        api_key=api_key,
        key_name=wi.get("vip_key_name", ""),
        _connect_url=wi.get("vip_connect_url", ""),
        _tmpdir="",  # Workers don't own the temp dir; controller cleans up.
    )
    config.stash[_auth_session_key] = session


def pytest_configure_node(node) -> None:
    """xdist controller hook: share interactive-auth credentials with workers."""
    auth = node.config.stash.get(_auth_session_key, None)
    if auth is not None:
        node.workerinput["vip_interactive_auth"] = True
        node.workerinput["vip_api_key"] = auth.api_key or ""
        node.workerinput["vip_storage_state"] = str(auth.storage_state_path)
        node.workerinput["vip_key_name"] = auth.key_name
        node.workerinput["vip_connect_url"] = auth._connect_url


def pytest_sessionstart(session: pytest.Session) -> None:
    """Add extension directories to sys.path so their conftest / modules
    are importable, and register them for collection."""
    ext_dirs = session.config.stash.get(_ext_dirs_key, [])
    for d in ext_dirs:
        p = Path(d).resolve()
        if p.is_dir():
            str_p = str(p)
            if str_p not in sys.path:
                sys.path.insert(0, str_p)
            # Tell pytest to collect from this directory as well.
            session.config.args.append(str_p)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Deselect tests whose product is not configured, skip tests whose
    version requirement is not met, and ensure prerequisites run first."""
    vip_cfg: VIPConfig = config.stash[_vip_config_key]
    no_auth = config.getoption("--no-auth", default=False)

    # Sort so prerequisites run before everything else, and assign xdist
    # groups so that each product's tests land on a dedicated worker.
    # Tests for unconfigured products are deselected (excluded entirely)
    # rather than skipped, so they don't appear in the report.
    prerequisites: list[pytest.Item] = []
    rest: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if _should_deselect_for_product(item, vip_cfg):
            deselected.append(item)
            continue
        if no_auth and _requires_auth(item):
            deselected.append(item)
            continue
        _maybe_skip_for_version(item, vip_cfg)
        _assign_xdist_group(item)
        _stash_scenario_metadata(item)
        if item.get_closest_marker("prerequisites"):
            prerequisites.append(item)
        else:
            rest.append(item)
    items[:] = prerequisites + rest
    if deselected:
        config.hook.pytest_deselected(items=deselected)


# Directories whose tests get a dedicated xdist worker.
_PRODUCT_DIRS = {"connect", "workbench", "package_manager"}


def _assign_xdist_group(item: pytest.Item) -> None:
    """Assign an ``xdist_group`` marker so each product runs on its own worker.

    Tests under ``tests/connect/``, ``tests/workbench/``, or
    ``tests/package_manager/`` are grouped by directory name.  Everything
    else (prerequisites, cross_product, performance, security) lands in a
    shared ``general`` group.
    """
    fspath = getattr(item, "path", None) or Path()
    dir_name = fspath.parent.name
    group = dir_name if dir_name in _PRODUCT_DIRS else "general"
    item.add_marker(pytest.mark.xdist_group(group))


# Mapping from "Given" step name prefix to product config key.
# Steps like "Connect is configured in vip.toml" gate a scenario on
# a product being configured; when it isn't, the test should be
# deselected rather than skipped so it doesn't clutter the output.
_GIVEN_PRODUCT_STEPS = {
    "Connect is configured": "connect",
    "Workbench is configured": "workbench",
    "Package Manager is configured": "package_manager",
}

# Display name → config key for parameterized "<product>" placeholders.
_PRODUCT_DISPLAY_NAMES = {
    "Connect": "connect",
    "Workbench": "workbench",
    "Package Manager": "package_manager",
}


def _get_bdd_param_product(item: pytest.Item) -> str | None:
    """Extract the product display name from a pytest-bdd parameterized item.

    pytest-bdd stores Scenario Outline examples in ``callspec.params`` as
    ``{'_pytest_bdd_example': {'product': 'Connect', ...}}``.
    """
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return None
    example = callspec.params.get("_pytest_bdd_example")
    if isinstance(example, dict):
        return example.get("product")
    return None


def _should_deselect_for_product(item: pytest.Item, cfg: VIPConfig) -> bool:
    """Return True if *item* should be deselected because its product is not configured."""
    # Check explicit product markers (@connect, @workbench, @package_manager).
    for marker_name, product_key in _PRODUCT_MARKERS.items():
        marker = item.get_closest_marker(marker_name)
        if marker is not None:
            pc = cfg.product_config(product_key)
            if not pc.is_configured:
                return True

    # Check BDD scenario "Given" steps for product-configuration guards.
    fn = getattr(item, "obj", None)
    scenario_obj = getattr(fn, "__scenario__", None) if fn else None
    if scenario_obj is not None:
        for step in getattr(scenario_obj, "steps", []):
            if step.type != "given":
                continue
            # Direct match: "Connect is configured in vip.toml"
            for prefix, product_key in _GIVEN_PRODUCT_STEPS.items():
                if step.name.startswith(prefix):
                    pc = cfg.product_config(product_key)
                    if not pc.is_configured:
                        return True
            # Parameterized match: "<product> is configured in vip.toml"
            # pytest-bdd stores Scenario Outline examples in callspec.params
            # as {'_pytest_bdd_example': {'product': 'Connect', ...}}.
            if step.name.startswith("<") and "is configured" in step.name:
                product_name = _get_bdd_param_product(item)
                if product_name:
                    product_key = _PRODUCT_DISPLAY_NAMES.get(product_name)
                    if product_key:
                        pc = cfg.product_config(product_key)
                        if not pc.is_configured:
                            return True

    return False


# Products that require username/password credentials.
_AUTH_PRODUCTS = {"connect", "workbench"}


def _requires_auth(item: pytest.Item) -> bool:
    """Return True if *item* requires authentication credentials."""
    # Explicit product markers.
    for marker_name in _AUTH_PRODUCTS:
        if item.get_closest_marker(marker_name) is not None:
            return True

    # BDD "Given" steps that reference an auth-required product.
    fn = getattr(item, "obj", None)
    scenario_obj = getattr(fn, "__scenario__", None) if fn else None
    if scenario_obj is not None:
        for step in getattr(scenario_obj, "steps", []):
            if step.type != "given":
                continue
            for prefix, product_key in _GIVEN_PRODUCT_STEPS.items():
                if product_key in _AUTH_PRODUCTS and step.name.startswith(prefix):
                    return True

    return False


def _maybe_skip_for_version(item: pytest.Item, cfg: VIPConfig) -> None:
    marker = item.get_closest_marker("min_version")
    if marker is None:
        return

    product = marker.kwargs.get("product") or (marker.args[0] if marker.args else None)
    version = marker.kwargs.get("version") or (marker.args[1] if len(marker.args) > 1 else None)
    if not product or not version:
        return

    try:
        pc = cfg.product_config(product)
    except ValueError:
        return

    if pc.version is None:
        # Version unknown - run the test optimistically.
        return

    if _version_tuple(pc.version) < _version_tuple(version):
        item.add_marker(
            pytest.mark.skip(reason=f"{product} version {pc.version} < required {version}")
        )


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple."""
    return tuple(int(m.group()) if (m := re.match(r"\d+", seg)) else 0 for seg in v.split("."))


# ---------------------------------------------------------------------------
# JSON results for Quarto report
# ---------------------------------------------------------------------------


_scenario_stash_key = pytest.StashKey[dict[str, str | None]]()


def _stash_scenario_metadata(item: pytest.Item) -> None:
    """Extract pytest-bdd scenario metadata and stash it on the item."""
    scenario_title = None
    feature_description = None

    # pytest-bdd stores scenario info as __scenario__ on the wrapper function.
    fn = getattr(item, "obj", None)
    scenario_obj = getattr(fn, "__scenario__", None) if fn else None
    if scenario_obj is not None:
        scenario_title = getattr(scenario_obj, "name", None)
        feature_obj = getattr(scenario_obj, "feature", None)
        if feature_obj is not None:
            feature_description = getattr(feature_obj, "description", None)

    item.stash[_scenario_stash_key] = {
        "scenario_title": scenario_title,
        "feature_description": feature_description,
    }


def _extract_exception_info(longrepr: str) -> tuple[str, str]:
    """Extract (exception_type, message) from a longrepr string.

    Handles four common formats:
    - pytest's ``E   ExcType: message`` lines in tracebacks
    - pytest's bare ``E   assert ...`` lines (assertion rewriting, no type prefix)
    - pytest's bare ``E   ExcType`` lines (exception with no message)
    - plain ``ExcType: message`` strings (e.g. from failures.json)

    Returns ``("UnknownError", <truncated string>)`` if parsing fails.
    """
    # Look for pytest's "E   ExcType: message" line format (message may be empty).
    # Multi-line assertion messages produce continuation "E   ..." lines that
    # we join together so the concise output keeps the full details.
    m = re.search(
        r"^E\s+([\w.]+(?:Error|Exception|Timeout|Refused)?):\s*(.*)",
        longrepr,
        re.MULTILINE,
    )
    if m:
        msg_lines = [m.group(2).strip()]
        # Gather only the contiguous block of E-lines that follow immediately.
        for line in longrepr[m.end() :].lstrip("\n").splitlines():
            cont = re.match(r"^E\s{3,}(.+)", line)
            if not cont:
                break
            msg_lines.append(cont.group(1).strip())
        return m.group(1), " ".join(line for line in msg_lines if line)

    # Bare assertion from pytest's assertion rewriting: "E   assert 403 == 200"
    m = re.search(r"^E\s+(assert\s+.+)", longrepr, re.MULTILINE)
    if m:
        return "AssertionError", m.group(1).strip()

    # Bare exception type with no message: "E   ValueError" (no colon)
    m = re.search(
        r"^E\s+([\w.]+(?:Error|Exception|Timeout|Refused)?)\s*$",
        longrepr,
        re.MULTILINE,
    )
    if m:
        return m.group(1), ""

    # Fall back to "ExcType: message" at the start of the string.
    m = re.match(r"([\w.]+(?:Error|Exception|Timeout|Refused)?):\s*(.+)", longrepr.strip())
    if m:
        return m.group(1), m.group(2).strip()

    return "UnknownError", longrepr.strip()[:200]


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
        if is_assertion:
            return f"{test_name}: {exc_type}"
        return f"{test_name}: an unexpected error occurred: {exc_type}"

    if is_assertion:
        # Custom assertion messages are user-actionable — show them directly.
        # Bare assertions (e.g. "assert 403 == 200") still need the type prefix.
        if exc_message.lstrip().startswith("assert "):
            return f"{test_name}: AssertionError: {exc_message}"
        return f"{test_name}: {exc_message}"

    return f"{test_name}: an unexpected error occurred: {exc_type}: {exc_message}"


# ---------------------------------------------------------------------------
# Long-running test heartbeat
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL = 30  # seconds between "still running" messages


class _Heartbeat:
    """Print periodic elapsed-time messages while a test is running."""

    def __init__(self, writer, interval: int = _HEARTBEAT_INTERVAL):
        self._writer = writer
        self._interval = interval
        self._start: float = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._start = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            elapsed = int(time.monotonic() - self._start)
            self._writer(f"  ... still running ({elapsed}s)")


# Exposed so that code importing gevent/locust (which calls monkey.patch_all)
# can stop the heartbeat thread first to avoid a deadlock.
_current_heartbeat: _Heartbeat | None = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem) -> None:  # noqa: ARG001
    """Print periodic heartbeat messages while a test is running."""
    global _current_heartbeat
    heartbeat: _Heartbeat | None = None
    if _active_config is not None:
        tr = _active_config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            heartbeat = _Heartbeat(tr.write_line)
            heartbeat.start()
            _current_heartbeat = heartbeat
    try:
        yield
    finally:
        if heartbeat is not None:
            heartbeat.stop()
            _current_heartbeat = None


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


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # xdist workers skip all session-end cleanup (controller handles it).
    is_worker = hasattr(session.config, "workerinput")

    if not is_worker:
        # Clean up interactive auth session (delete API key, remove temp files)
        auth_session = session.config.stash.get(_auth_session_key, None)
        if auth_session is not None:
            auth_session.cleanup()

    report_path = session.config.getoption("--vip-report")
    if not report_path or is_worker:
        return

    cfg: VIPConfig = session.config.stash[_vip_config_key]
    results = session.config.stash.get(_results_key, [])

    # Include product metadata for the report.
    # Derive product list from _PRODUCT_MARKERS so new products are picked up automatically.
    products: dict[str, dict[str, Any]] = {}
    for name in _PRODUCT_MARKERS.values():
        pc = cfg.product_config(name)
        products[name] = {
            "enabled": pc.enabled,
            "url": pc.url,
            "version": pc.version,
            "configured": pc.is_configured,
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deployment_name": cfg.deployment_name,
        "exit_status": exitstatus,
        "products": products,
        "results": results,
    }

    try:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        warnings.warn(f"VIP: could not write report to {report_path}: {exc}", stacklevel=1)
        return

    # Write failures.json alongside results.json so report rendering is idempotent.
    failures = [r for r in results if r.get("outcome") == "failed"]
    if failures:
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
        failures_path = p.parent / "failures.json"
        try:
            failures_path.write_text(json.dumps(failures_payload, indent=2) + "\n")
        except OSError as exc:
            warnings.warn(
                f"VIP: could not write failures report to {failures_path}: {exc}", stacklevel=1
            )
