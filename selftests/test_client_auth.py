"""Tests for vip.client_auth — pluggable HTTP-client auth registry."""

from __future__ import annotations

import httpx
import pytest

from vip import client_auth
from vip.client_auth import (
    build_client_auth,
    get_client_auth_factory,
    register_client_auth,
)
from vip.clients.base import BaseClient
from vip.config import VIPConfig


@pytest.fixture(autouse=True)
def _restore_registry():
    """Snapshot and restore the module-level registry around each test."""
    saved = dict(client_auth._CLIENT_AUTH_FACTORIES)
    try:
        yield
    finally:
        client_auth._CLIENT_AUTH_FACTORIES.clear()
        client_auth._CLIENT_AUTH_FACTORIES.update(saved)


class _DummyAuth(httpx.Auth):
    def auth_flow(self, request):
        yield request


def _config(idp: str = "") -> VIPConfig:
    cfg = VIPConfig()
    cfg.auth.idp = idp
    return cfg


class TestRegistry:
    def test_register_and_get_round_trip(self):
        def factory(config, product, base_url):
            return None

        register_client_auth("snowflake", factory)
        assert get_client_auth_factory("snowflake") is factory

    def test_lookup_is_case_insensitive(self):
        def factory(config, product, base_url):
            return None

        register_client_auth("Snowflake", factory)
        assert get_client_auth_factory("  SNOWFLAKE ") is factory

    def test_unregistered_returns_none(self):
        assert get_client_auth_factory("nope") is None


class TestBuildClientAuth:
    def test_no_idp_returns_none(self):
        assert build_client_auth(_config(""), "connect", "https://x") is None

    def test_unregistered_idp_returns_none(self):
        assert build_client_auth(_config("snowflake"), "connect", "https://x") is None

    def test_invokes_factory_with_product_and_url(self):
        calls = []
        auth = _DummyAuth()

        def factory(config, product, base_url):
            calls.append((product, base_url))
            return auth

        register_client_auth("snowflake", factory)
        result = build_client_auth(_config("snowflake"), "workbench", "https://wb")
        assert result is auth
        assert calls == [("workbench", "https://wb")]

    def test_factory_may_return_none(self):
        register_client_auth("snowflake", lambda c, p, u: None)
        assert build_client_auth(_config("snowflake"), "connect", "https://x") is None


class TestBaseClientAuthInjection:
    def test_auth_is_forwarded_to_httpx_client(self):
        auth = _DummyAuth()
        client = BaseClient("https://example.com", auth=auth)
        try:
            assert client._client.auth is auth
        finally:
            client.close()

    def test_default_has_no_auth(self):
        client = BaseClient("https://example.com", auth_header_value="Key abc")
        try:
            # httpx represents "no auth" as its internal sentinel, not our auth.
            assert not isinstance(client._client.auth, _DummyAuth)
        finally:
            client.close()
