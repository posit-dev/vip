"""Selftests must never inherit the developer's or runner's proxy environment.

``vip.proxy.build_proxy_map(None)`` reads the ambient
``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY``/``NO_PROXY``, and
``resolve_url_scheme`` now changes behavior when a proxy applies (it refuses the
https->http downgrade, because the raw-socket TLS tiebreak would bypass the
proxy). So on a machine with a proxy exported, every selftest that exercises
scheme resolution silently takes a different branch and fails -- and the probes
attempt real connections through it, which is why the suite also slows to a
crawl.

The autouse fixture in ``selftests/conftest.py`` clears those variables for the
whole selftest package. These tests guard that fixture: they are what fails if
someone removes it, rather than twenty unrelated tests failing confusingly on
one developer's laptop.
"""

from __future__ import annotations

import os

from vip.proxy import ProxyConfig, build_proxy_map, proxy_for_url

_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def test_no_proxy_env_visible_to_selftests():
    """No proxy variable leaks in from the ambient environment."""
    leaked = {var: os.environ[var] for var in _PROXY_VARS if var in os.environ}
    assert leaked == {}


def test_default_proxy_config_resolves_to_direct():
    """The default ProxyConfig must resolve to "everything direct" in selftests.

    This is the property the scheme-resolution tests depend on: with an empty
    map, ``resolve_url_scheme`` takes its no-proxy branch and the https->http
    downgrade behaves as those tests expect.
    """
    assert build_proxy_map(ProxyConfig()) == {}
    assert build_proxy_map(None) == {}
    assert proxy_for_url("https://connect.example.com", build_proxy_map(None)) is None
