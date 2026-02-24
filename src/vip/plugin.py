"""VIP pytest plugin.

Registered via the ``pytest11`` entry point so it activates automatically
when the ``vip`` package is installed.

Responsibilities:
- Register custom markers.
- Add CLI options (``--vip-config``, ``--vip-extensions``, ``--vip-report``,
  ``--interactive-auth``).
- Auto-skip tests whose product is not configured.
- Auto-skip tests whose product version doesn't meet ``min_version``.
- Ensure prerequisites run before other tests.
- Collect extension directories.
- Write a JSON results file for the Quarto report.
- Handle interactive OIDC authentication for external identity providers.
"""

from __future__ import annotations

import json
import sys
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
_auth_state_key = pytest.StashKey[str | None]()
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
        default=None,
        help="Write a JSON results file at this path for Quarto report generation.",
    )
    group.addoption(
        "--interactive-auth",
        action="store_true",
        default=False,
        help="Launch a browser for manual OIDC login before running tests.",
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

    # Load VIP config and stash it for fixtures / collection hooks.
    vip_cfg = load_config(config.getoption("--vip-config"))
    config.stash[_vip_config_key] = vip_cfg

    # Initialize per-session results list (avoids module-level global).
    config.stash[_results_key] = []

    # Merge extension dirs from config file and CLI.
    ext_dirs: list[str] = list(vip_cfg.extension_dirs)
    ext_dirs.extend(config.getoption("--vip-extensions") or [])
    config.stash[_ext_dirs_key] = ext_dirs

    # Handle interactive auth — browser stays open for the session
    config.stash[_auth_session_key] = None
    if config.getoption("--interactive-auth"):
        if not vip_cfg.connect.url:
            raise pytest.UsageError(
                "--interactive-auth requires Connect URL to be configured in vip.toml"
            )
        from vip.auth import start_interactive_auth

        session = start_interactive_auth(vip_cfg.connect.url)
        config.stash[_auth_session_key] = session
        config.stash[_auth_state_key] = str(session.storage_state_path)
        if session.api_key:
            vip_cfg.connect.api_key = session.api_key
    else:
        config.stash[_auth_state_key] = None


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
    """Skip tests whose product is not configured or whose version
    requirement is not met, and ensure prerequisites run first."""
    vip_cfg: VIPConfig = config.stash[_vip_config_key]
    using_interactive_auth = config.stash.get(_auth_state_key, None) is not None

    # Sort so prerequisites run before everything else.
    prerequisites: list[pytest.Item] = []
    rest: list[pytest.Item] = []
    for item in items:
        _maybe_skip_for_product(item, vip_cfg)
        _maybe_skip_for_version(item, vip_cfg)
        _maybe_skip_credential_check(item, using_interactive_auth)
        if item.get_closest_marker("prerequisites"):
            prerequisites.append(item)
        else:
            rest.append(item)
    items[:] = prerequisites + rest


def _maybe_skip_credential_check(item: pytest.Item, using_interactive_auth: bool) -> None:
    """Skip the credential prerequisite test when using interactive auth."""
    if using_interactive_auth and "test_credentials_provided" in item.nodeid:
        item.add_marker(
            pytest.mark.skip(reason="--interactive-auth is active, credential check not needed")
        )


def _maybe_skip_for_product(item: pytest.Item, cfg: VIPConfig) -> None:
    for marker_name, product_key in _PRODUCT_MARKERS.items():
        marker = item.get_closest_marker(marker_name)
        if marker is not None:
            pc = cfg.product_config(product_key)
            if not pc.is_configured:
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"{product_key} is not configured (set url in vip.toml)"
                    )
                )


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
    parts: list[int] = []
    for segment in v.split("."):
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


# ---------------------------------------------------------------------------
# JSON results for Quarto report
# ---------------------------------------------------------------------------


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or (report.when == "setup" and report.skipped):
        if _active_config is None:
            return
        results = _active_config.stash.get(_results_key, None)
        if results is None:
            return
        markers: list[str] = []
        if hasattr(report, "item"):
            try:
                markers = [m.name for m in report.item.iter_markers()]  # type: ignore[attr-defined]
            except Exception:
                pass
        results.append(
            {
                "nodeid": report.nodeid,
                "outcome": report.outcome,
                "duration": report.duration,
                "longrepr": str(report.longrepr) if report.longrepr else None,
                "markers": markers,
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Clean up interactive auth session (delete API key, close browser)
    auth_session = session.config.stash.get(_auth_session_key, None)
    if auth_session is not None:
        auth_session.cleanup()

    report_path = session.config.getoption("--vip-report")
    if not report_path:
        return

    cfg: VIPConfig = session.config.stash[_vip_config_key]
    results = session.config.stash.get(_results_key, [])

    # Include product metadata for the report.
    products: dict[str, dict[str, Any]] = {}
    for name in ("connect", "workbench", "package_manager"):
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
