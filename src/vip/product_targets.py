"""Discover the Posit product versions this VIP release targets.

Rather than hand-maintaining a list, the targeted versions are derived from the
``@pytest.mark.min_version`` markers in the shipped test suite: the version a
release targets for a product is the highest ``min_version`` floor any test
requires for that product. Because the numbers *are* the markers, this can't
drift from the tests. Surfaced by ``vip --product-versions``.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterator
from pathlib import Path

from vip.version import ProductVersion

# Product id (as used in ``@pytest.mark.min_version`` markers) -> display name.
# Unknown ids fall back to the raw id.
_DISPLAY_NAMES = {
    "connect": "Connect",
    "workbench": "Workbench",
    "package_manager": "Package Manager",
}


def _display_name(product_id: str) -> str:
    return _DISPLAY_NAMES.get(product_id, product_id)


def _tests_root() -> Path | None:
    """Locate the installed ``vip_tests`` package directory, or None."""
    spec = importlib.util.find_spec("vip_tests")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def _string_arg(call: ast.Call, name: str, position: int) -> str | None:
    """Extract a string ``min_version`` argument by keyword or position."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            value = kw.value.value
            return value if isinstance(value, str) else None
    if position < len(call.args):
        node = call.args[position]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
    return None


def _iter_markers(path: Path) -> Iterator[tuple[str, str]]:
    """Yield ``(product, version)`` from ``@pytest.mark.min_version`` decorators."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return
    for node in ast.walk(tree):
        for dec in getattr(node, "decorator_list", []):
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr == "min_version"):
                continue
            product = _string_arg(dec, "product", 0)
            version = _string_arg(dec, "version", 1)
            if product and version:
                yield product, version


def scan_targeted_product_versions() -> dict[str, str]:
    """Return ``{display_name: highest_version}`` across the suite's markers.

    Malformed versions are skipped. Returns an empty dict when the test suite
    is not installed alongside vip.
    """
    root = _tests_root()
    if root is None:
        return {}

    highest: dict[str, ProductVersion] = {}
    raw: dict[str, str] = {}
    for py in root.rglob("*.py"):
        for product, version in _iter_markers(py):
            try:
                parsed = ProductVersion(version)
            except ValueError:
                continue
            if product not in highest or parsed > highest[product]:
                highest[product] = parsed
                raw[product] = version

    return {_display_name(pid): raw[pid] for pid in sorted(raw, key=_display_name)}
