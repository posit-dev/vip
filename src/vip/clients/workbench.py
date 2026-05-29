"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from vip.clients.base import BaseClient

_VIP_SESSION_PREFIXES = ("VIP ", "_vip_")


def is_vip_session(label: str) -> bool:
    """Return True if *label* matches a VIP-created session naming pattern.

    VIP names sessions either ``"VIP <file> - <worker>-<ns>"`` (most tests,
    via ``unique_session_name``) or ``"_vip_cap_<ts>_..."`` (capacity tests).
    """
    return any(label.startswith(prefix) for prefix in _VIP_SESSION_PREFIXES)


class WorkbenchClient(BaseClient):
    """Minimal Workbench HTTP wrapper."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        timeout: float = 30.0,
        insecure: bool = False,
        ca_bundle: Path | None = None,
    ) -> None:
        super().__init__(
            base_url,
            auth_header_value=f"Key {api_key}" if api_key else "",
            timeout=timeout,
            insecure=insecure,
            ca_bundle=ca_bundle,
        )

    # -- Health / info ------------------------------------------------------

    def health(self) -> int:
        """Return the HTTP status code of the health endpoint."""
        resp = self._client.get("/health-check")
        return resp.status_code

    def server_settings(self) -> dict[str, Any]:
        """Return server settings including version information.

        Returns the parsed JSON from ``/api/server/settings``.  Raises
        ``httpx.HTTPStatusError`` if the endpoint is not reachable.
        """
        resp = self._client.get("/api/server/settings")
        resp.raise_for_status()
        return resp.json()

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

    def quit_vip_sessions(self, *, retries: int = 2, settle_seconds: float = 0.5) -> int:
        """Force-quit every VIP-named session reachable by this client.

        Lists sessions, quits only those matching :func:`is_vip_session`
        (DELETE, falling back to suspend), then re-lists to confirm they are
        gone and retries up to *retries* times.  Sessions are matched by label
        so a real user's sessions are never touched.  Never raises; returns the
        number of successful quit/suspend calls.

        Authentication uses whatever this client already carries (cookies set
        via :meth:`set_cookies`, or an API-key Authorization header).
        """
        quit_count = 0
        for attempt in range(retries):
            try:
                resp = self._client.get("/api/sessions")
            except Exception:
                break
            sessions = resp.json() if resp.status_code == 200 else []
            targets = [s for s in sessions if is_vip_session(s.get("label", ""))]
            if not targets:
                break
            for session in targets:
                sid = session.get("id") or session.get("session_id", "")
                if not sid:
                    continue
                for method, path in (
                    ("DELETE", f"/api/sessions/{sid}"),
                    ("POST", f"/api/sessions/{sid}/suspend"),
                ):
                    try:
                        r = self._client.request(method, path)
                        if r.status_code < 400:
                            quit_count += 1
                            break
                    except Exception:
                        continue
            if attempt < retries - 1:
                time.sleep(settle_seconds)
        return quit_count
