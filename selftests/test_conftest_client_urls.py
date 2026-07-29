"""Tests for vip_tests.conftest._resolved_url.

``connect_client``/``workbench_client``/``pm_client`` (and their companion
``connect_url``/``workbench_url``/``pm_url`` fixtures) are the seam that talks
to the server for the ``--api-auth``/``--no-auth`` paths, where no browser
auth flow runs to resolve a scheme-less URL first (see ``vip.auth.
resolve_url_scheme`` and issue #537). ``_resolved_url`` is the shared helper
those fixtures call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from vip.config import ConnectConfig, VIPConfig
from vip_tests.conftest import _resolved_url


class TestResolvedUrl:
    def setup_method(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()

    def test_explicit_scheme_never_probes(self):
        pc = ConnectConfig(url="https://connect.example.com")
        vip_config = VIPConfig()

        with patch("httpx.get") as mock_get:
            url = _resolved_url(pc, vip_config)

        assert url == "https://connect.example.com"
        mock_get.assert_not_called()

    def test_inferred_scheme_kept_when_https_answers(self):
        pc = ConnectConfig(url="connect.example.com")
        assert pc.url_scheme_inferred is True
        vip_config = VIPConfig()

        with patch("httpx.get", return_value=MagicMock(status_code=200)):
            url = _resolved_url(pc, vip_config)

        assert url == "https://connect.example.com"
        assert pc.url == "https://connect.example.com"

    def test_inferred_scheme_falls_back_and_mutates_config_in_place(self):
        """The fixture's whole point is that pc.url is corrected in place so
        every other fixture that reads it afterward sees the same value."""
        import httpx

        pc = ConnectConfig(url="connect.example.com")
        vip_config = VIPConfig()

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            url = _resolved_url(pc, vip_config)

        assert url == "http://connect.example.com"
        assert pc.url == "http://connect.example.com"

    def test_second_call_does_not_probe_again(self):
        """resolve_url_scheme's cache means calling this from more than one
        fixture (connect_client, then connect_url) for the same product
        probes the network only once."""
        import httpx

        pc = ConnectConfig(url="connect.example.com")
        vip_config = VIPConfig()

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            first = _resolved_url(pc, vip_config)
            second = _resolved_url(pc, vip_config)

        assert first == second == "http://connect.example.com"
        mock_get.assert_called_once()

    def test_insecure_and_ca_bundle_are_forwarded(self, tmp_path):
        ca = tmp_path / "ca.pem"
        pc = ConnectConfig(url="connect.example.com")
        vip_config = VIPConfig(ca_bundle=ca)

        with patch("httpx.get", return_value=MagicMock(status_code=200)) as mock_get:
            _resolved_url(pc, vip_config)

        assert mock_get.call_args.kwargs["verify"] == str(ca)
