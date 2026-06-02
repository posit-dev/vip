"""Shared base class for VIP HTTP clients."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import TypeVar

import httpx

_T = TypeVar("_T", bound="BaseClient")


class BaseClient:
    """Minimal shared base for Posit product HTTP clients.

    Parameters
    ----------
    base_url:
        Root URL of the product (trailing ``/`` is stripped).
    auth_header_value:
        Full value for the ``Authorization`` header (e.g. ``"Key abc123"``
        or ``"Bearer tok"``).  Pass an empty string to omit the header.
    auth:
        Optional ``httpx.Auth`` applied per request.  Use for schemes that
        cannot be expressed as a single static header — e.g. a token that
        must be refreshed or re-derived per target host (Snowflake Native
        App SPCS ingress).  When set it takes precedence over
        *auth_header_value*; typically only one of the two is provided.
    api_prefix:
        Path segment appended to *base_url* when constructing the internal
        httpx client (e.g. ``"/__api__"`` for Connect).  The ``base_url``
        property still returns the original URL without this prefix.
    timeout:
        Default request timeout in seconds.
    insecure:
        Disable TLS certificate verification (equivalent to ``curl -k``).
        **Use only in trusted environments** — this silently ignores
        certificate errors including MITM attacks.
    ca_bundle:
        Path to a custom CA certificate bundle (PEM) to trust in addition
        to the system roots.  Useful for self-signed or corporate CAs.
    extra_headers:
        Additional static default headers for the httpx client.  Use for
        app-level auth that must NOT occupy the ``Authorization`` header
        because *auth* already owns it — e.g. Connect's ``X-RSC-Authorization``
        when reached through an SPCS ingress that consumes ``Authorization``.
    """

    def __init__(
        self,
        base_url: str,
        auth_header_value: str = "",
        api_prefix: str = "",
        timeout: float = 30.0,
        insecure: bool = False,
        ca_bundle: Path | None = None,
        auth: httpx.Auth | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if auth_header_value:
            headers["Authorization"] = auth_header_value
        if extra_headers:
            headers.update(extra_headers)
        # Compute the httpx ``verify`` argument from TLS config:
        #   insecure=True  → False  (skip all certificate verification)
        #   ca_bundle set  → str path  (use custom CA bundle)
        #   default        → True  (use system trust store)
        if insecure:
            verify: bool | str = False
        elif ca_bundle is not None:
            verify = str(ca_bundle)
        else:
            verify = True
        # Store for subclasses that need to create ad-hoc httpx requests with
        # the same TLS configuration and per-request auth (e.g. fetch_content).
        self._verify = verify
        self._auth = auth
        # HTTPTransport retries cover connection-level failures (e.g. refused
        # connections, broken pipes).  HTTP-level errors (502/503/504) are not
        # retried here — ConnectClient.wait_for_task already handles those at
        # the application level.
        #
        # IMPORTANT: when a custom ``transport`` is passed to ``httpx.Client``,
        # httpx ignores the client-level ``verify`` argument — SSL config must
        # be set on the transport itself.  Pass ``verify`` to HTTPTransport so
        # that insecure / ca_bundle settings are actually honored.
        transport = httpx.HTTPTransport(retries=3, verify=verify)
        self._client = httpx.Client(
            base_url=f"{self._base_url}{api_prefix}",
            headers=headers,
            timeout=timeout,
            transport=transport,
            auth=auth,
        )

    @property
    def base_url(self) -> str:
        """Root URL of the product, without any API path prefix."""
        return self._base_url

    @property
    def verify(self) -> bool | str:
        """The httpx ``verify`` value for this client's TLS configuration.

        ``False`` means certificate verification is disabled (insecure mode).
        A string is the path to a custom CA bundle.
        ``True`` means the system trust store is used (default).
        """
        return self._verify

    @property
    def auth(self) -> httpx.Auth | None:
        """The per-request httpx auth for this client, if any.

        Subclasses and tests that issue ad-hoc httpx requests (bypassing the
        internal ``_client``) must pass this so the request carries the same
        per-host auth — e.g. the Snowflake SPCS ingress token. Without it the
        ingress redirects unauthenticated requests to its OAuth login (302).
        """
        return self._auth

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def __enter__(self: _T) -> _T:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
