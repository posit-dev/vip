"""VIP pytest plugin.

Registered via the ``pytest11`` entry point so it activates automatically
when the ``vip`` package is installed.

Responsibilities:
- Register custom markers.
- Add CLI options (``--vip-config``, ``--vip-extensions``, ``--vip-report``).
- Auto-skip tests whose product is not configured.
- Auto-skip tests whose product version doesn't meet ``min_version``.
- Collect extension directories.
- Write a JSON results file for the Quarto report.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from vip.config import VIPConfig, load_config

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


def pytest_configure(config: pytest.Config) -> None:
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

    # Merge extension dirs from config file and CLI.
    ext_dirs: list[str] = list(vip_cfg.extension_dirs)
    ext_dirs.extend(config.getoption("--vip-extensions") or [])
    config.stash[_ext_dirs_key] = ext_dirs


_vip_config_key = pytest.StashKey[VIPConfig]()
_ext_dirs_key = pytest.StashKey[list[str]]()

# Mapping from pytest marker name to product config key.
_PRODUCT_MARKERS = {
    "connect": "connect",
    "workbench": "workbench",
    "package_manager": "package_manager",
}


def pytest_collect_file(parent: pytest.Collector, file_path: Path) -> None:
    """Collect test files from extension directories."""
    # Extension collection is handled at session level; this hook is a no-op
    # placeholder for future use.


def pytest_sessionstart(session: pytest.Session) -> None:
    """Add extension directories to sys.path so their conftest / modules
    are importable, and register them for collection."""
    import sys

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
    requirement is not met."""
    vip_cfg: VIPConfig = config.stash[_vip_config_key]

    for item in items:
        _maybe_skip_for_product(item, vip_cfg)
        _maybe_skip_for_version(item, vip_cfg)


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

_results: list[dict[str, Any]] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or (report.when == "setup" and report.skipped):
        _results.append(
            {
                "nodeid": report.nodeid,
                "outcome": report.outcome,
                "duration": report.duration,
                "longrepr": str(report.longrepr) if report.longrepr else None,
                "markers": (
                    [m.name for m in report.item.iter_markers()]  # type: ignore[attr-defined]
                    if hasattr(report, "item")
                    else []
                ),
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    report_path = session.config.getoption("--vip-report")
    if report_path:
        cfg: VIPConfig = session.config.stash[_vip_config_key]
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "deployment_name": cfg.deployment_name,
            "exit_status": exitstatus,
            "results": _results,
        }
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
