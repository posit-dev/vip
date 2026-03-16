"""Shared base class for VIP HTTP clients."""

from __future__ import annotations

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
    api_prefix:
        Path segment appended to *base_url* when constructing the internal
        httpx client (e.g. ``"/__api__"`` for Connect).  The ``base_url``
        property still returns the original URL without this prefix.
    timeout:
        Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        auth_header_value: str = "",
        api_prefix: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if auth_header_value:
            headers["Authorization"] = auth_header_value
        # HTTPTransport retries cover connection-level failures (e.g. refused
        # connections, broken pipes).  HTTP-level errors (502/503/504) are not
        # retried here — ConnectClient.wait_for_task already handles those at
        # the application level.
        transport = httpx.HTTPTransport(retries=3)
        self._client = httpx.Client(
            base_url=f"{self._base_url}{api_prefix}",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    @property
    def base_url(self) -> str:
        """Root URL of the product, without any API path prefix."""
        return self._base_url

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
