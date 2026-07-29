"""Tests for the scheme-resolution wiring in vip_tests/conftest.py.

``connect_client``/``workbench_client``/``pm_client`` (and their companion
``connect_url``/``workbench_url``/``pm_url`` fixtures) are the seam that talks
to the server for the ``--api-auth``/``--no-auth`` paths, where no browser
auth flow runs to resolve a scheme-less URL first (see ``vip.auth.
resolve_url_scheme`` and issue #537).

A type-design review on #562 pointed out that ``resolve_url_scheme`` used to
take a bare ``url: str`` and trust the caller to have checked
``ProductConfig.url_scheme_inferred`` first. It now takes the whole
``ProductConfig`` and checks provenance itself (see ``TestResolveUrlScheme``
in ``test_auth.py`` for the full behavior matrix), which means there is no
longer a separate conftest.py helper with its own logic to test in
isolation -- these fixtures are now a single direct call. What is still
worth pinning down here is that each fixture passes the *right*
``ProductConfig`` (connect's, not workbench's or package_manager's) and the
right TLS settings through to ``resolve_url_scheme``.

The ``connect_url``/``workbench_url``/``pm_url`` fixtures are called via
``.__wrapped__`` to invoke the underlying function directly, bypassing
pytest's "fixtures cannot be called directly" guard -- they take only
``vip_config`` as a parameter, so this needs no ``request``/stash setup.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from vip.config import ConnectConfig, PackageManagerConfig, VIPConfig, WorkbenchConfig
from vip_tests import conftest


class TestUrlFixturesResolveTheRightProductConfig:
    def setup_method(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()

    def test_connect_url_resolves_connect_config(self):
        vip_config = VIPConfig(connect=ConnectConfig(url="connect.example.com"))

        with patch("httpx.get", return_value=MagicMock(status_code=200)):
            url = conftest.connect_url.__wrapped__(vip_config)

        assert url == "https://connect.example.com"

    def test_connect_url_falls_back_when_unreachable(self):
        vip_config = VIPConfig(connect=ConnectConfig(url="connect.example.com"))

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            url = conftest.connect_url.__wrapped__(vip_config)

        assert url == "http://connect.example.com"
        assert vip_config.connect.url == "http://connect.example.com"

    def test_connect_url_with_explicit_scheme_never_probes(self):
        vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

        with patch("httpx.get") as mock_get:
            url = conftest.connect_url.__wrapped__(vip_config)

        assert url == "https://connect.example.com"
        mock_get.assert_not_called()

    def test_workbench_url_resolves_workbench_config_not_connect(self):
        """Regression guard: passing the wrong ProductConfig (e.g. connect's
        instead of workbench's) would silently resolve/mutate the wrong
        product's URL."""
        vip_config = VIPConfig(
            connect=ConnectConfig(url="https://connect.example.com"),
            workbench=WorkbenchConfig(url="workbench.example.com"),
        )

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            url = conftest.workbench_url.__wrapped__(vip_config)

        assert url == "http://workbench.example.com"
        assert vip_config.workbench.url == "http://workbench.example.com"
        # The unrelated Connect config must be untouched.
        assert vip_config.connect.url == "https://connect.example.com"

    def test_pm_url_resolves_package_manager_config(self):
        vip_config = VIPConfig(package_manager=PackageManagerConfig(url="pm.example.com"))

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            url = conftest.pm_url.__wrapped__(vip_config)

        assert url == "http://pm.example.com"

    def test_insecure_and_ca_bundle_are_forwarded(self, tmp_path):
        ca = tmp_path / "ca.pem"
        vip_config = VIPConfig(
            connect=ConnectConfig(url="connect.example.com"),
            insecure=False,
            ca_bundle=ca,
        )

        with patch("httpx.get", return_value=MagicMock(status_code=200)) as mock_get:
            conftest.connect_url.__wrapped__(vip_config)

        assert mock_get.call_args.kwargs["verify"] == str(ca)
