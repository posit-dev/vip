"""Tests for vip.http_semantics helpers.

Placed in selftests/ so they run in CI without a real Posit deployment.
"""

from __future__ import annotations

import httpx
import pytest

from vip.http_semantics import denied_by_external_gateway


def _resp(
    status_code: int,
    *,
    request_url: str = "https://connect.example.com/__api__/v1/content",
    location: str | None = None,
) -> httpx.Response:
    """Build a minimal httpx.Response with a real Request so resp.url works."""
    headers: dict[str, str] = {}
    if location is not None:
        headers["location"] = location
    return httpx.Response(
        status_code=status_code,
        headers=headers,
        content=b"",
        request=httpx.Request("GET", request_url),
    )


class TestDeniedByExternalGateway:
    """denied_by_external_gateway returns True only when a 3xx redirect's
    Location header points to a different hostname than the request host.
    A same-host redirect, a non-redirect, or a missing Location are all False.
    """

    def test_cross_host_307_returns_true(self):
        """Classic gateway intercept: Connect request redirected to external IdP."""
        resp = _resp(307, location="https://idp.example.com/oauth2/authorize?client_id=vip")
        assert denied_by_external_gateway(resp) is True

    def test_same_host_307_returns_false(self):
        """A redirect on the same Connect host is NOT a gateway intercept."""
        resp = _resp(307, location="https://connect.example.com/__login__?return_to=/")
        assert denied_by_external_gateway(resp) is False

    def test_401_returns_false(self):
        """Direct 401 from Connect — no gateway involved."""
        resp = _resp(401)
        assert denied_by_external_gateway(resp) is False

    def test_404_returns_false(self):
        """Direct 404 from Connect — no gateway involved."""
        resp = _resp(404)
        assert denied_by_external_gateway(resp) is False

    def test_200_returns_false(self):
        """Successful response — not a redirect at all."""
        resp = _resp(200)
        assert denied_by_external_gateway(resp) is False

    def test_cross_host_302_returns_true(self):
        """302 Found to a different host is also an external gateway pattern."""
        resp = _resp(302, location="https://sso.corp.example.com/login")
        assert denied_by_external_gateway(resp) is True

    def test_cross_host_303_returns_true(self):
        """303 See Other to a different host."""
        resp = _resp(303, location="https://okta.example.com/sso/saml")
        assert denied_by_external_gateway(resp) is True

    def test_cross_host_308_returns_true(self):
        """308 Permanent Redirect to a different host."""
        resp = _resp(308, location="https://idp.example.com/login")
        assert denied_by_external_gateway(resp) is True

    def test_cross_host_301_returns_true(self):
        """301 Moved Permanently to a different host."""
        resp = _resp(301, location="https://idp.example.com/login")
        assert denied_by_external_gateway(resp) is True

    def test_missing_location_returns_false(self):
        """307 without a Location header — degenerate redirect, not a gateway."""
        resp = _resp(307)  # no location kwarg
        assert denied_by_external_gateway(resp) is False

    def test_relative_location_returns_false(self):
        """A relative Location has no host component — treated as same-host."""
        resp = _resp(307, location="/__login__?return_to=/")
        assert denied_by_external_gateway(resp) is False

    @pytest.mark.parametrize("status_code", [100, 201, 204, 400, 403, 500, 503])
    def test_non_redirect_codes_return_false(self, status_code):
        """Non-3xx status codes always return False regardless of headers."""
        resp = _resp(status_code, location="https://idp.example.com/login")
        assert denied_by_external_gateway(resp) is False
