"""Connect API-key minting, deletion, and stale-key cleanup."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Page,
)

from vip.auth.scheme import _httpx_verify_env_aware
from vip.proxy import (
    ProxyConfig,
    build_proxy_map,
    proxy_for_url,
)
from vip.timeouts import scaled

# Prefix for VIP-managed API keys.  A timestamp is appended per run.
_KEY_NAME_PREFIX = "_vip_interactive_"


# Orphan keys younger than this are left alone so a concurrent ``vip verify``
# run does not have its freshly-minted key yanked out from under it.  Cleanup
# is for keys whose process crashed before running ``cleanup()``; anything
# recent enough to still belong to a live run is out of scope.
_ORPHAN_MIN_AGE_SECONDS = 3600


def _delete_api_key(
    connect_url: str,
    api_key: str,
    key_name: str,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> None:
    """Delete the VIP API key using the key itself for authentication."""
    verify = _httpx_verify_env_aware(insecure, ca_bundle)

    base = connect_url.rstrip("/")
    delete_proxy = proxy_for_url(base, build_proxy_map(proxy))
    with httpx.Client(
        base_url=f"{base}/__api__",
        headers={"Authorization": f"Key {api_key}"},
        timeout=scaled(10.0),
        verify=verify,
        proxy=delete_proxy,
        trust_env=False,
    ) as client:
        for keys_path in ("/v1/user/api_keys", "/keys"):
            resp = client.get(keys_path)
            if resp.status_code == 404:
                continue
            if not resp.is_success:
                print(f">>> Warning: {keys_path} returned HTTP {resp.status_code}")
                continue
            for k in resp.json():
                if k.get("name") == key_name:
                    del_resp = client.delete(f"{keys_path}/{k['id']}")
                    if del_resp.is_success:
                        print(">>> API key deleted.\n")
                    else:
                        print(
                            f">>> Warning: DELETE {keys_path}/{k['id']}"
                            f" returned {del_resp.status_code}"
                        )
                    return
            break
        print(">>> Warning: Could not find API key to delete.\n")


_XSRF_COOKIE_NAMES = ("RSC-XSRF", "RSC-XSRF-legacy")


def _xsrf_from_page(page: Page, request_url: str) -> str:
    """Read the XSRF cookie value from the browser context for ``request_url``.

    Connect's XSRF check compares the cookie value to the ``X-Rsc-Xsrf``
    header.  Production deployments use one of two cookie names:

    * ``RSC-XSRF`` — default on fresh installs.
    * ``RSC-XSRF-legacy`` — set when the server runs in legacy cookie
      mode (e.g. ``connect.posit.it``).  The paired session cookie is
      ``rsconnect-legacy``.  The header name stays ``X-Rsc-Xsrf``.

    Playwright's ``cookies(url)`` filter implements RFC 6265 path
    matching: ``Path=/__api__/`` only matches request paths *under*
    ``/__api__/``.  Pass the actual endpoint URL (e.g.
    ``.../__api__/v1/user``) — not the bare ``/__api__`` base — or
    cookies set with a trailing-slash path get silently excluded and
    Connect replies ``HTTP 403 XSRF token mismatch``.  Reading via the
    cookie jar rather than ``document.cookie`` also handles
    ``HttpOnly`` uniformly.
    """
    try:
        jar = page.context.cookies(request_url) or []
    except PlaywrightError:
        return ""
    by_name = {c.get("name"): c.get("value") or "" for c in jar}
    for name in _XSRF_COOKIE_NAMES:
        if by_name.get(name):
            return by_name[name]
    return ""


def _summarize_cookies(jar: Sequence[Mapping[str, Any]]) -> list[dict]:
    return [
        {
            "name": c.get("name"),
            "domain": c.get("domain"),
            "path": c.get("path"),
            "httpOnly": c.get("httpOnly"),
            "len": len(c.get("value") or ""),
        }
        for c in jar
    ]


def _log_mint_cookie_diagnostic(page: Page, request_url: str) -> None:
    """Print what we see in the browser when minting fails.

    Turns an opaque XSRF mismatch into actionable evidence: the page
    URL, the full jar (to spot cross-domain shadows), the jar filtered
    to the actual endpoint URL under ``/__api__/`` (what truly rides
    the request, respecting RFC 6265 path matching), and
    ``document.cookie`` names.  If these two cookie lists disagree on
    ``RSC-XSRF`` / ``RSC-XSRF-legacy``, the mismatch is almost certainly
    another domain — or a path-scoped cookie — poisoning the unfiltered
    view.
    """
    try:
        current_url = page.url
    except PlaywrightError:
        current_url = "<unknown>"
    print(f">>> Mint diagnostic: browser is on {current_url}")
    try:
        jar = page.context.cookies() or []
        print(f">>> Mint diagnostic: full cookie jar ({len(jar)} entries):")
        for entry in _summarize_cookies(jar):
            print(f"    {entry}")
    except PlaywrightError as exc:
        print(f">>> Mint diagnostic: could not read cookie jar: {exc}")
    try:
        scoped = page.context.cookies(request_url) or []
        print(f">>> Mint diagnostic: cookies sent to {request_url} ({len(scoped)} entries):")
        for entry in _summarize_cookies(scoped):
            print(f"    {entry}")
    except PlaywrightError as exc:
        print(f">>> Mint diagnostic: could not read scoped cookies: {exc}")
    try:
        doc_cookie = page.evaluate("() => document.cookie") or ""
        doc_names = [p.strip().partition("=")[0] for p in doc_cookie.split(";") if p.strip()]
        print(f">>> Mint diagnostic: document.cookie names: {doc_names}")
    except PlaywrightError as exc:
        print(f">>> Mint diagnostic: could not read document.cookie: {exc}")


def _response_text(resp) -> str:
    """Read a response body, tolerating both Playwright and httpx shapes.

    Playwright's ``APIResponse.text`` is a method; httpx's is a property.
    Tests sometimes stub it as a plain string.  Duck-type all three.
    """
    text_attr = getattr(resp, "text", None)
    if callable(text_attr):
        return text_attr() or ""
    return text_attr or ""


def _delete_stale_vip_keys(client, guid: str) -> None:
    """Delete ``_vip_interactive_<ts>`` keys older than
    :data:`_ORPHAN_MIN_AGE_SECONDS`.

    Best-effort: network failures and unparseable names are swallowed so a
    single stuck orphan does not block fresh key creation.  Keys younger than
    the threshold are left alone because they probably belong to another
    ``vip verify`` still running.

    *client* is an ``httpx.Client`` already configured with the correct
    ``base_url``, ``verify``, ``cookies``, and ``headers``.  The caller
    constructs it and owns its lifecycle.
    """
    try:
        list_resp = client.get(f"/v1/users/{guid}/keys")
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        print(f">>> Warning: listing stale keys failed: {exc}")
        return
    if not list_resp.is_success:
        return

    now = int(time.time())
    try:
        entries = list_resp.json()
    except ValueError:
        return
    if not isinstance(entries, list):
        print(f">>> Warning: key list response was {type(entries).__name__}, not list.")
        return

    for k in entries:
        if not isinstance(k, dict):
            continue
        name = k.get("name") or ""
        key_id = k.get("id")
        if not name.startswith(_KEY_NAME_PREFIX) or not key_id:
            continue
        suffix = name[len(_KEY_NAME_PREFIX) :]
        try:
            created_ts = int(suffix)
        except ValueError:
            # Legacy key without a timestamp suffix — treat as old.
            created_ts = 0
        if now - created_ts < _ORPHAN_MIN_AGE_SECONDS:
            continue  # belongs to a concurrent run
        try:
            client.delete(f"/v1/users/{guid}/keys/{key_id}")
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            print(f">>> Warning: could not delete stale key {key_id}: {exc}")


def _content_type(resp) -> str:
    """Return the response Content-Type header (or ``"<none>"``) tolerantly.

    Test stubs sometimes use a plain ``MagicMock`` for ``headers``; fall back
    to ``"<none>"`` so the diagnostic line stays readable rather than printing
    a mock repr.
    """
    try:
        headers = getattr(resp, "headers", None) or {}
        value = headers.get("content-type", "<none>")
    except (AttributeError, TypeError):
        return "<none>"
    return value if isinstance(value, str) else "<none>"


def _probe_server_settings(client, base: str, me_status: int, connect_url: str) -> None:
    """Probe ``/__api__/server_settings`` after a mint failure on ``/v1/user``.

    ``/server_settings`` is unauthenticated and lives on the same Connect
    API mount as ``/v1/user``, so if it 404s too, we are simply not hitting
    Connect — the configured ``connect_url`` has the wrong path prefix.
    This turns a confusing "API key minting failed" into a concrete pointer
    at the misconfigured URL (e.g. ``--connect-url .../connect`` when the
    server really lives at the host root).

    Best-effort: any transport error is logged and swallowed.
    """
    try:
        probe = client.get("/server_settings")
    except httpx.HTTPError as exc:
        print(f">>> Mint diagnostic: /server_settings probe failed: {exc}")
        return
    probe_ct = _content_type(probe)
    probe_url = f"{base}/server_settings"
    print(
        f">>> Mint diagnostic: GET {probe_url} returned HTTP "
        f"{probe.status_code} (content-type: {probe_ct})"
    )
    if me_status == 404 and probe.status_code == 404:
        print(
            f">>> Mint diagnostic: both /__api__ endpoints returned 404 — "
            f"the configured connect_url ({connect_url}) likely has the "
            f"wrong path prefix. Try removing any sub-path (e.g. '/connect') "
            f"from --connect-url, or ask the administrator where Connect's "
            f"/__api__/ is mounted."
        )


def _body_snippet(resp, limit: int = 200) -> str:
    """Return a short, single-line preview of an HTTP response body.

    Connect's API error responses include ``error``/``code`` fields that name
    the actual failure reason (CSRF rejection, MFA step-up, etc.).  Including
    a trimmed body snippet in failure warnings turns opaque ``HTTP 403`` into
    something the user can act on.
    """
    try:
        text = _response_text(resp).strip()
    except (PlaywrightError, AttributeError):
        return "<unreadable body>"
    text = " ".join(text.split())
    return text[:limit] if text else "<empty body>"


def _resolve_connect_api_base(
    connect_url: str,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> str:
    """Return a Connect URL whose ``/__api__/`` mount actually responds.

    Some deployments serve the dashboard under a sub-path (``/connect/``)
    but keep the API at the host root.  ``<connect_url>/__api__/`` then
    404s while ``<host>/__api__/`` returns 200.  When that mismatch is
    detected, switch to the host root for API traffic; otherwise return
    the original URL unchanged.

    ``/__api__/server_settings`` is unauthenticated, so probing does not
    need browser cookies.  On any error or ambiguous result, returns the
    original URL so the existing mint diagnostics still run.

    Both probes route through the same proxy the API clients will use, pinned
    with ``trust_env=False`` so the resolved per-URL proxy (which honours
    NO_PROXY) is authoritative rather than httpx re-reading the environment.
    """
    if not connect_url:
        return connect_url

    parsed = urlparse(connect_url)
    sub_path = (parsed.path or "").strip("/")
    if not sub_path:
        # Already at host root — nothing to fall back to.
        return connect_url

    verify = _httpx_verify_env_aware(insecure, ca_bundle)
    proxy_map = build_proxy_map(proxy)
    primary = connect_url.rstrip("/") + "/__api__/server_settings"
    try:
        primary_resp = httpx.get(
            primary,
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            proxy=proxy_for_url(primary, proxy_map),
            trust_env=False,
        )
    except httpx.HTTPError:
        return connect_url
    if primary_resp.status_code == 200:
        return connect_url

    root = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    secondary = root + "/__api__/server_settings"
    try:
        secondary_resp = httpx.get(
            secondary,
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            proxy=proxy_for_url(secondary, proxy_map),
            trust_env=False,
        )
    except httpx.HTTPError:
        return connect_url
    if secondary_resp.status_code != 200:
        return connect_url

    ct = secondary_resp.headers.get("content-type", "") or ""
    if "json" not in ct.lower():
        return connect_url
    try:
        body = secondary_resp.json()
    except (ValueError, KeyError):
        return connect_url
    if not isinstance(body, dict):
        # JSON 200 that isn't an object (list, scalar, null) cannot be
        # Connect's server_settings payload — treat as ambiguous and
        # keep the original URL.  Without this guard ``body.get(...)``
        # raises ``AttributeError`` and crashes auth.
        return connect_url

    # Require a *positive* match between the root API's advertised
    # ``dashboard_path`` and the sub-path on the configured URL before
    # switching.  A missing or empty ``dashboard_path`` is treated as
    # unverified — keep the original URL rather than blindly routing
    # mint traffic at a JSON endpoint that merely happens to answer 200.
    dashboard_path = (body.get("dashboard_path") or "").strip("/")
    if dashboard_path != sub_path:
        return connect_url

    print(
        f">>> Connect dashboard at {connect_url} but API at {root}/__api__/; "
        f"using {root} for API calls."
    )
    return root


def _create_api_key_via_session(
    page: Page,
    connect_url: str,
    key_name: str,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> str | None:
    """Create a Connect API key by reusing the browser's authenticated session.

    Extracts session cookies from ``page.context.cookies()`` and uses an
    ``httpx.Client`` for all API requests so that ``insecure`` / ``ca_bundle``
    TLS settings are honoured.  Playwright's ``APIRequestContext``
    (``page.context.request``) does not expose a ``verify`` equivalent and
    cannot accept a custom CA bundle, which caused ``CERTIFICATE_VERIFY_FAILED``
    errors when ``--insecure`` was set (issue #239).

    The client is constructed with ``follow_redirects=True`` to match
    ``_resolve_connect_api_base``'s probes: a deployment that redirects
    HTTP -> HTTPS (or drops/adds a trailing slash) would otherwise turn a
    301/302 into a treated-as-failure response here (issue #537).

    The XSRF token is still read from the browser's cookie jar via
    :func:`_xsrf_from_page` and sent as the ``X-Rsc-Xsrf`` request header —
    Connect's double-submit CSRF check requires the header and the cookie to
    match.  The cookie is named ``RSC-XSRF`` on fresh installs and
    ``RSC-XSRF-legacy`` on servers running in legacy cookie mode.

    Hits ``/__api__/v1/users/{guid}/keys`` — the same endpoint the Connect
    dashboard's "+ New API Key" button uses.  See
    https://docs.posit.co/connect/api/ (operationId: createKey).

    Before creating the new key, deletes any lingering ``_vip_interactive_*``
    keys left over from previous runs that crashed before cleanup.  Keys
    younger than :data:`_ORPHAN_MIN_AGE_SECONDS` are skipped so we do not
    delete a concurrent run's live key.

    Returns the API key string, or ``None`` on failure (no exception).

    Note: full end-to-end verification (actual TLS rejection → acceptance with
    ``--insecure``) requires a real self-signed Connect deployment and is not
    covered by selftests.  The ``_httpx_verify`` unit tests confirm the verify
    plumbing; manual testing against a staging cluster is needed to close #239.
    """
    verify = _httpx_verify_env_aware(insecure, ca_bundle)
    base = connect_url.rstrip("/") + "/__api__"
    me_url = f"{base}/v1/user"
    # Mint through the same proxy the product clients will use, resolved for this
    # host (honours NO_PROXY). trust_env=False makes that decision authoritative.
    mint_proxy = proxy_for_url(base, build_proxy_map(proxy))
    # Scope cookie lookup to an actual endpoint path.  RFC 6265 cookie
    # path matching means ``Path=/__api__/`` does *not* match a request
    # to ``/__api__`` (no trailing slash).  Using ``me_url`` matches
    # whatever path the server set the cookie under.
    xsrf = _xsrf_from_page(page, me_url)
    headers = {"X-Rsc-Xsrf": xsrf} if xsrf else {}

    # Build a cookie dict from the browser's session for the Connect API base.
    # We extract cookies for ``me_url`` (under ``/__api__/``) so that
    # path-scoped cookies (e.g. ``Path=/__api__/``) are included — Playwright's
    # RFC 6265-compliant filter excludes them when queried against the bare
    # ``/__api__`` base (no trailing slash).
    try:
        raw_cookies = page.context.cookies(me_url) or []
    except PlaywrightError:
        raw_cookies = []
    cookies = {c["name"]: c["value"] for c in raw_cookies if c.get("name")}

    try:
        with httpx.Client(
            base_url=base,
            headers=headers,
            cookies=cookies,
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            proxy=mint_proxy,
            trust_env=False,
        ) as client:
            me_resp = client.get("/v1/user")
            if not me_resp.is_success:
                me_ct = _content_type(me_resp)
                print(
                    f">>> Warning: GET {me_url} returned HTTP "
                    f"{me_resp.status_code} (content-type: {me_ct}): "
                    f"{_body_snippet(me_resp)}"
                )
                xsrf_preview = f"{xsrf[:4]}…(len={len(xsrf)})" if xsrf else "<none>"
                print(f">>> Mint diagnostic: X-Rsc-Xsrf header was {xsrf_preview}")
                _log_mint_cookie_diagnostic(page, me_url)
                _probe_server_settings(client, base, me_resp.status_code, connect_url)
                return None
            guid = me_resp.json().get("guid")
            if not guid:
                print(">>> Warning: Connect did not return a user guid.")
                return None

            _delete_stale_vip_keys(client, guid)

            create_resp = client.post(
                f"/v1/users/{guid}/keys",
                json={"name": key_name},
            )
            if not create_resp.is_success:
                print(
                    f">>> Warning: POST /v1/users/{guid}/keys returned HTTP "
                    f"{create_resp.status_code}: {_body_snippet(create_resp)}"
                )
                return None

            created = create_resp.json()
            if not isinstance(created, dict):
                # A 301/302 on the POST is followed as a GET -- httpx
                # downgrades the method exactly as browsers and curl do, and
                # only 307/308 preserve it.  The downgraded GET lands on the
                # same path, which is the key-*listing* route, so a JSON array
                # comes back instead of the created key.  Without this guard
                # ``.get("key")`` raises ``AttributeError``, which is not in
                # the caught tuple below and so crashes auth outright (#561).
                print(
                    f">>> Warning: POST /v1/users/{guid}/keys returned a "
                    f"{type(created).__name__}, not an object. A proxy most "
                    "likely redirected the request with 301/302, which turns "
                    "the POST into a GET of the key-listing route. Configure "
                    "the proxy to redirect with 307/308, or point --connect-url "
                    "at the final URL so no redirect is needed."
                )
                return None

            api_key = created.get("key")
            if not api_key:
                print(">>> Warning: Connect response did not include a key string.")
                return None

            print(">>> Connect API key created.\n")
            return api_key
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        # httpx.HTTPError catches both transport-level failures (DNS, TCP,
        # TLS, timeouts -- httpx.RequestError) and HTTP status errors
        # (httpx.HTTPStatusError).  Mirrors the prior PlaywrightError
        # handling: the function is documented to return None on failure
        # rather than raising, so vip verify can emit a warning instead of
        # crashing during auth setup.
        print(f">>> Warning: Could not create API key: {exc}")
        return None
