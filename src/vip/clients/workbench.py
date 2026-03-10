"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
"""

from __future__ import annotations

from typing import Any

import httpx


class WorkbenchClient:
    """Minimal Workbench HTTP wrapper."""

    def __init__(self, base_url: str, api_key: str = "", *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Key {api_key}"
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

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

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """Set cookies on the client instance for authenticated requests."""
        self._client.cookies.update(cookies)

    def list_sessions(self) -> list[dict[str, Any]]:
        """List active sessions for the authenticated user."""
        resp = self._client.get("/api/sessions")
        if resp.status_code == 200:
            return resp.json()
        return []

    def quit_session(self, session_id: str) -> bool:
        """Attempt to quit/suspend a session.  Returns True on success."""
        for method, path in (
            ("DELETE", f"/api/sessions/{session_id}"),
            ("POST", f"/api/sessions/{session_id}/suspend"),
        ):
            try:
                resp = self._client.request(method, path)
                if resp.status_code < 400:
                    return True
            except Exception:
                continue
        return False

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()
