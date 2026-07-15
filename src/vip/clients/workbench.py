"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from vip.clients.base import BaseClient

logger = logging.getLogger(__name__)

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
        timeout: float | None = None,
        insecure: bool = False,
        ca_bundle: Path | None = None,
        auth: httpx.Auth | None = None,
        cookies: httpx.Cookies | None = None,
    ) -> None:
        super().__init__(
            base_url,
            auth_header_value=f"Key {api_key}" if api_key else "",
            timeout=timeout,
            insecure=insecure,
            ca_bundle=ca_bundle,
            auth=auth,
            cookies=cookies,
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

    def sessions_api_reachable(self) -> bool:
        """Return True only if ``/api/sessions`` returns a usable session list.

        The API-based cleanup (:meth:`list_sessions` / :meth:`quit_vip_sessions`)
        works only when this endpoint responds ``200`` with a JSON **array**.
        Some deployments instead 404 (SPA fallback), serve ``200`` HTML, or
        redirect to login (``302``) — all status codes that are not a usable
        list.  Returning True for those would wrongly suppress the UI-driven
        cleanup fallback and orphan VIP sessions, so we require a ``200`` whose
        body parses as a ``list``.  Returns False otherwise or on any transport
        exception; never raises.
        """
        try:
            resp = self._client.get("/api/sessions")
            if resp.status_code != 200:
                return False
            return isinstance(resp.json(), list)
        except Exception:
            return False

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

        Lists sessions and quits only those matching :func:`is_vip_session`
        (via :meth:`quit_session`: DELETE, falling back to suspend), then
        re-lists and repeats the quit-and-verify cycle up to *retries* times
        while VIP sessions remain.  A failed *list* call (non-200 or a thrown
        exception) ends the run without retrying.  Sessions are matched by
        label so a real user's sessions are never touched.  Never raises
        (malformed or unexpected API payloads are ignored); returns the number
        of distinct sessions for which a quit/suspend call succeeded.

        Authentication uses whatever this client already carries (cookies set
        via :meth:`set_cookies`, or an API-key Authorization header).

        :meth:`quit_session` treats any HTTP status below 400 as success
        without confirming the session actually terminated — some
        deployments accept the DELETE/suspend call but leave the session
        running (issue #467).  If the retry loop runs out its full budget
        without ever observing an empty listing (i.e. VIP sessions were still
        listed on the final attempt), a ``WARNING`` is logged naming the
        labels/ids still present so the leak is visible instead of silent.
        No warning is logged when a listing already confirmed nothing
        remains (the loop exited via the "no targets" break).
        """
        quit_ids: set[str] = set()
        exhausted_with_targets = False
        for attempt in range(retries):
            try:
                resp = self._client.get("/api/sessions")
                sessions = resp.json() if resp.status_code == 200 else []
            except Exception:
                # Connection error, non-JSON body, etc. — give up this run.
                break
            if not isinstance(sessions, list):
                break
            # Coerce label to str so a null/non-string label never raises.
            targets = [
                s
                for s in sessions
                if isinstance(s, dict) and is_vip_session(str(s.get("label") or ""))
            ]
            if not targets:
                break
            for session in targets:
                sid = session.get("id") or session.get("session_id") or ""
                if sid and self.quit_session(sid):
                    quit_ids.add(str(sid))
            if attempt < retries - 1:
                time.sleep(settle_seconds)
            exhausted_with_targets = attempt == retries - 1
        if exhausted_with_targets:
            self._warn_if_vip_sessions_remain()
        return len(quit_ids)

    def _warn_if_vip_sessions_remain(self) -> None:
        """Log a WARNING naming any VIP session still listed right now.

        Called after :meth:`quit_vip_sessions` exhausts its retries with VIP
        sessions still present on the last listing, so a session that quietly
        survived every quit attempt is surfaced loudly instead of the caller
        just getting back a count.  Best-effort: swallows all exceptions and
        never raises.
        """
        try:
            resp = self._client.get("/api/sessions")
            sessions = resp.json() if resp.status_code == 200 else []
        except Exception:
            return
        if not isinstance(sessions, list):
            return
        remaining = [
            s for s in sessions if isinstance(s, dict) and is_vip_session(str(s.get("label") or ""))
        ]
        if not remaining:
            return
        details = ", ".join(
            f"{s.get('label')!r} (id={s.get('id') or s.get('session_id') or '?'})"
            for s in remaining
        )
        logger.warning(
            "quit_vip_sessions: %d VIP-named Workbench session(s) still present after cleanup: %s",
            len(remaining),
            details,
        )
