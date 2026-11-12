"""Collection: product deselection, auth-mode filtering, xdist grouping, and
``min_version`` skips.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from vip.config import VIPConfig
from vip.plugin.results import (
    _PRODUCT_MARKERS,
    _REQUIRES_MARKERS,
    _scenario_given_steps,
    _stash_scenario_metadata,
)
from vip.stash import _version_na_key, _vip_config_key
from vip.version import ProductVersion


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
    warn_guards = _warns_on_this_process(config)
    warned: set[tuple[str, str]] = set()
    for item in items:
        if warn_guards:
            _warn_untagged_product_guard(item, warned)
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


# Every marker that names a product *item* needs: ``@connect`` and ``@requires_connect`` alike.
_ALL_PRODUCT_MARKERS = {**_PRODUCT_MARKERS, **_REQUIRES_MARKERS}


def _required_products(item: pytest.Item) -> set[str]:
    """Return the config keys of every product *item* needs, from its product
    markers (``@connect``) and its ``@requires_*`` tags.
    """
    return {
        key
        for name, key in _ALL_PRODUCT_MARKERS.items()
        if item.get_closest_marker(name) is not None
    }


def _should_deselect_for_product(item: pytest.Item, cfg: VIPConfig) -> bool:
    """Return True if *item* should be deselected because its product is not configured."""
    return any(not cfg.product_config(key).is_configured for key in _required_products(item))


# Given-step prefix → product config key.
_GIVEN_PRODUCT_PREFIXES = {
    "Connect is configured": "connect",
    "Workbench is configured": "workbench",
    "Package Manager is configured": "package_manager",
}


def _given_products(item: pytest.Item) -> set[str]:
    """Return the config keys named by *item*'s product Given steps, Background steps included."""
    return {
        key
        for text in _scenario_given_steps(item)
        for prefix, key in _GIVEN_PRODUCT_PREFIXES.items()
        if text.startswith(prefix)
    }


def _warns_on_this_process(config: pytest.Config) -> bool:
    """Return False on every xdist worker but ``gw0``, since each worker collects every item."""
    workerinput = getattr(config, "workerinput", None)
    return workerinput is None or workerinput.get("workerid") == "gw0"


def _warn_untagged_product_guard(item: pytest.Item, warned: set[tuple[str, str]]) -> None:
    """Warn once per scenario when a product Given step has no matching product marker or
    ``@requires_*`` tag.

    Only tags deselect, so such a scenario runs even when the product isn't configured, and a
    custom guard step that doesn't skip then fails against a ``None`` client. *warned* holds the
    (scenario, tags) pairs already reported, so an outline's rows share one warning.
    """
    missing = _given_products(item) - _required_products(item)
    if not missing:
        return
    scenario_id = item.nodeid.split("[", 1)[0]
    tags = ", ".join(f"@requires_{key}" for key in sorted(missing))
    if (scenario_id, tags) in warned:
        return
    warned.add((scenario_id, tags))
    where = (
        "the scenario, or to the Examples block holding those rows"
        if getattr(item, "callspec", None) is not None
        else "the scenario"
    )
    warnings.warn(
        f"VIP: {scenario_id} has a product Given step but no {tags} tag, so it is not "
        f"deselected when that product is not configured. Add the tag to {where}.",
        stacklevel=1,
    )


# Products that require username/password credentials.
_AUTH_PRODUCTS = {"connect", "workbench"}


def _requires_auth(item: pytest.Item) -> bool:
    """Return True if *item* requires username/password credentials.

    Only product markers count: ``@requires_*`` tags mean "this product is
    configured", which credential-free checks such as TLS probes also need.
    """
    return any(item.get_closest_marker(name) is not None for name in _AUTH_PRODUCTS)


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
