"""Small HTTP-semantic helpers used across VIP step definitions and clients.

Keeping these here (rather than inside BDD step modules) lets selftests
import them without triggering pytest-bdd scenario collection side-effects.
"""

from __future__ import annotations

import httpx


def denied_by_external_gateway(resp: httpx.Response) -> bool:
    """Return True when a redirect points to a DIFFERENT host than the request.

    This is the signature of an external OIDC/SSO gateway intercepting an
    unauthenticated request (e.g. an Okta proxy redirecting to the IdP login
    page).  A same-host redirect does NOT qualify — that could be an internal
    Connect login redirect, not a gateway intercept.

    Only 3xx status codes with a ``Location`` header that resolves to a
    different hostname trigger ``True``; all other responses (401, 404, 200,
    same-host redirects, missing Location) return ``False``.
    """
    if resp.status_code not in (301, 302, 303, 307, 308):
        return False
    loc = resp.headers.get("location", "")
    if not loc:
        return False
    target = httpx.URL(loc)
    return bool(target.host) and target.host != resp.url.host
