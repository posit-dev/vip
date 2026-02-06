"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
"""

from __future__ import annotations

from typing import Any

import httpx


class WorkbenchClient:
    """Minimal Workbench HTTP wrapper."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- Health / info ------------------------------------------------------

    def health(self) -> int:
        """Return the HTTP status code of the health endpoint."""
        resp = self._client.get("/health-check")
        return resp.status_code

    def server_info(self) -> dict[str, Any]:
        """Return basic server information (unauthenticated)."""
        resp = self._client.get("/api/server-info")
        if resp.status_code == 200:
            return resp.json()
        return {}

    # -- Sessions -----------------------------------------------------------

    def list_sessions(self, cookies: dict[str, str]) -> list[dict[str, Any]]:
        """List active sessions for the authenticated user."""
        resp = self._client.get("/api/sessions", cookies=cookies)
        if resp.status_code == 200:
            return resp.json()
        return []

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()
