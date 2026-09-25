"""Collection: product deselection, auth-mode filtering, xdist grouping, and
``min_version`` skips.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from vip.config import VIPConfig
from vip.gherkin import CONTROL_TAG_PREFIX
from vip.plugin.results import _PRODUCT_MARKERS, _stash_scenario_metadata
from vip.stash import _version_na_key, _vip_config_key
from vip.version import ProductVersion


@pytest.hookimpl(tryfirst=True)
def pytest_bdd_apply_tag(tag: str, function: object) -> object:
    """Turn an ``@control-<slug>`` Gherkin tag into one ``control(<slug>)`` mark.

    Every other tag returns None so pytest-bdd's own implementation runs
    instead -- ``@slow``, ``@connect`` and friends keep becoming marks named
    after themselves, which is what auto-skip and ``-m`` filtering rely on.

    Control slugs are chosen by the customer, so they cannot be registered by
    name ahead of time, and an unregistered mark warns by default and aborts
    collection outright under ``--strict-markers``, which regulated CI is
    likely to enable. Carrying the slug as an argument to one registered
    marker settles that without VIP having to predict the names: there is
    exactly one marker to register, and the slug is no longer a Python
    identifier, so ``@control-11.10(a)`` is as legal as ``@control-11-10-a``.
    """
    if not tag.startswith(CONTROL_TAG_PREFIX):
        return None
    return pytest.mark.control(tag[len(CONTROL_TAG_PREFIX) :])(function)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Deselect tests whose product is not configured, skip tests whose
    version requirement is not met, and ensure prerequisites run first.
    """
    vip_cfg: VIPConfig = config.stash[_vip_config_key]
    no_auth = config.getoption("--no-auth", default=False)
    api_auth = config.getoption("--api-auth", default=False)

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
        if api_auth and _requires_auth(item) and not _is_api_auth_only(item):
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

    Respects any existing ``xdist_group`` marker (set via conftest.py
    ``pytestmark`` or per-test decorators).  Otherwise, tests under
    ``tests/connect/``, ``tests/workbench/``, or ``tests/package_manager/``
    are grouped by directory name, and everything else (prerequisites,
    cross_product, performance, security) lands in a shared ``general`` group.
    """
    if item.get_closest_marker("xdist_group") is not None:
        return
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
                    resolved_key = _PRODUCT_DISPLAY_NAMES.get(product_name)
                    if resolved_key:
                        pc = cfg.product_config(resolved_key)
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


def _is_api_auth_only(item: pytest.Item) -> bool:
    """Return True if *item* is marked as requiring only API-key authentication."""
    return item.get_closest_marker("api_auth") is not None


def _maybe_skip_for_version(item: pytest.Item, cfg: VIPConfig) -> None:
    """Skip *item* when its ``min_version`` marker requirement is not met.

    When the deployed or required version cannot be parsed as a
    ``ProductVersion`` (including the "version unknown" case, ``pc.version
    is None``), the test is skipped and flagged as N/A-by-version rather
    than run optimistically or skipped indistinguishably from an ordinary
    skip. This surfaces version-detection gaps in the report instead of
    hiding them behind a possibly-spurious pass or a generic "skipped".
    """
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
        _skip_version_unknown(item, product, version, reason="version unknown")
        return

    try:
        deployed = ProductVersion(pc.version)
    except ValueError:
        _skip_version_unknown(
            item, product, version, reason=f"deployed version {pc.version!r} is unparseable"
        )
        return

    try:
        required = ProductVersion(version)
    except ValueError:
        _skip_version_unknown(
            item, product, version, reason=f"required version {version!r} is unparseable"
        )
        return

    if deployed < required:
        item.add_marker(
            pytest.mark.skip(reason=f"{product} version {pc.version} < required {version}")
        )


def _skip_version_unknown(item: pytest.Item, product: str, version: str, *, reason: str) -> None:
    """Skip *item* and flag it as N/A-by-version, warning about the gap."""
    item.stash[_version_na_key] = True
    item.add_marker(
        pytest.mark.skip(
            reason=f"VIP: version unknown for {product} — cannot evaluate "
            f"min_version(product={product!r}, version={version!r}) ({reason})"
        )
    )
    warnings.warn(
        f"VIP: cannot evaluate min_version(product={product!r}, version={version!r}) "
        f"for {item.nodeid} — {reason}. Skipping and marking N/A instead of running "
        "optimistically.",
        stacklevel=1,
    )
