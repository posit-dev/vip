"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from vip.clients.base import BaseClient

logger = logging.getLogger(__name__)

_VIP_SESSION_PREFIXES = ("VIP ", "_vip_")

# Workbench Admin API session activity_state values (docs-verified against
# docs.posit.co/ide/server-pro/admin/workbench_api). "running" is the ready
# state; "failed"/"killed" are terminal so a waiter can fail fast instead of
# waiting out the whole timeout.
SESSION_ACTIVE_STATE = "running"
SESSION_TERMINAL_FAILURE_STATES = ("failed", "killed")

# IDE display name -> the exact `workbench` param value accepted by
# launch_session. Case- and space-sensitive per the docs; do not "normalize".
WORKBENCH_IDE_VALUES = {
    "RStudio": "RStudio",
    "VS Code": "VS Code",
    "JupyterLab": "JupyterLab",
    "Jupyter Notebook": "Jupyter Notebook",
    "Positron": "Positron",
}


class WorkbenchSessionError(Exception):
    """A launched session never reached the active state.

    Raised by :meth:`WorkbenchClient.wait_for_active` when a session reaches a
    terminal failure state or never becomes active before the timeout, so the
    step layer can tell a deployment-side launch failure apart from an
    HTTP/privilege error (which surfaces as ``httpx.HTTPStatusError``).
    Parallels ``ResourceProfileDisabled`` in the workbench conftest.
    """


def is_vip_session(label: str) -> bool:
    """Return True if *label* matches a VIP-created session naming pattern.

    VIP names sessions either ``"VIP <file> - <worker>-<ns>"`` (most tests,
    via ``unique_session_name``) or ``"_vip_cap_<ts>_..."`` (capacity tests).
    """
    return any(label.startswith(prefix) for prefix in _VIP_SESSION_PREFIXES)


def _session_activity_state(result: Any) -> str | None:
    """Extract a single session's ``activity_state`` from a ``get_session`` result.

    The Admin API's ``get_session`` result can take a few shapes depending on
    the deployment/version: a single session dict carrying ``activity_state``
    directly, a list of such dicts, or a dict keyed by session id.  This
    normalizes those into the first ``activity_state`` string it finds, or
    ``None`` when the payload has no recognizable session (a transient shape
    the poll loop simply retries).
    """
    if isinstance(result, dict):
        state = result.get("activity_state")
        if isinstance(state, str):
            return state
        # dict keyed by session id -> session dict
        for value in result.values():
            if isinstance(value, dict) and isinstance(value.get("activity_state"), str):
                return value["activity_state"]
        return None
    if isinstance(result, list):
        for value in result:
            if isinstance(value, dict) and isinstance(value.get("activity_state"), str):
                return value["activity_state"]
    return None


class WorkbenchClient(BaseClient):
    """Minimal Workbench HTTP wrapper."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        auth_scheme: str = "Key",
        timeout: float | None = None,
        insecure: bool = False,
        ca_bundle: Path | None = None,
        auth: httpx.Auth | None = None,
        cookies: httpx.Cookies | None = None,
    ) -> None:
        # ``auth_scheme`` selects the ``Authorization`` header prefix. Default
        # ``"Key"`` preserves the pre-existing UI-cleanup behavior; the root
        # conftest passes ``"Bearer"`` for the Admin API (launch/get/stop),
        # which is docs-verified to require ``Authorization: Bearer <token>``.
        # The UI ``/api/sessions`` cleanup authenticates via cookies (see
        # :meth:`set_cookies`), so the header scheme does not affect it.
        super().__init__(
            base_url,
            auth_header_value=f"{auth_scheme} {api_key}" if api_key else "",
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

    def get_version(self) -> dict[str, Any]:
        """Return the Workbench Admin API version payload.

        ``GET /api/version`` → ``{"result": {"version": {...}, "features": ...}}``.
        Used by the API-auth readiness guard to confirm the Admin API is
        reachable and the Bearer token is accepted before any launch.  Raises
        ``httpx.HTTPStatusError`` on a non-2xx (the guard maps 401/403 to a
        skip and re-raises anything else).
        """
        resp = self._client.get("/api/version")
        resp.raise_for_status()
        return resp.json()

    # -- Admin API (session launch/inspect/stop) ----------------------------

    def launch_session(
        self,
        workbench: str,
        *,
        username: str | None = None,
        name: str | None = None,
        launch_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Launch a session via the Admin API and return the ``result`` dict.

        ``POST /api/launch_session`` with ``{"method": "launch_session",
        "kwparams": {...}}``.  The IDE is selected by the ``workbench`` field
        (one of :data:`WORKBENCH_IDE_VALUES`), *not* ``editor``.  A
        super-admin token may pass ``username`` to launch on behalf of that
        user.  ``name`` sets the session label (VIP passes a ``"VIP ..."`` name
        so :func:`is_vip_session` matches it for cleanup).  ``launch_parameters``
        is only required when Launcher-backed sessions are enabled; on Local
        Launcher it is omitted rather than fabricated.

        Raises ``httpx.HTTPStatusError`` on a non-2xx so the step layer can
        decide skip-vs-fail from the status code.  Returns the ``result``
        payload (``{"id", "url", "project_id"}``).
        """
        kwparams: dict[str, Any] = {"workbench": workbench}
        if username is not None:
            kwparams["username"] = username
        if name is not None:
            kwparams["name"] = name
        if launch_parameters is not None:
            kwparams["launch_parameters"] = launch_parameters
        resp = self._client.post(
            "/api/launch_session",
            json={"method": "launch_session", "kwparams": kwparams},
        )
        resp.raise_for_status()
        return resp.json()["result"]

    def get_session(
        self,
        session_id: str | None = None,
        *,
        username: str | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return the Admin API ``result`` for one or more sessions.

        ``POST /api/get_session``.  Note the field is ``session_id``
        (**singular**, comma-joined for multiple ids) — this differs from
        :meth:`stop_session`'s plural ``session_ids``; the API is inconsistent
        here.  The optional user filter is sent as ``user`` (from *username*).
        Raises ``httpx.HTTPStatusError`` on a non-2xx.
        """
        kwparams: dict[str, Any] = {}
        if session_id is not None:
            kwparams["session_id"] = session_id
        if username is not None:
            kwparams["user"] = username
        if fields is not None:
            kwparams["fields"] = fields
        resp = self._client.post(
            "/api/get_session",
            json={"method": "get_session", "kwparams": kwparams},
        )
        resp.raise_for_status()
        return resp.json()["result"]

    def stop_session(
        self,
        session_ids: str | Iterable[str],
        *,
        force_quit: bool = False,
        suspend: bool = False,
    ) -> bool:
        """Best-effort stop of one or more sessions via the Admin API.

        ``POST /api/stop_session`` with ``kwparams["session_ids"]``
        (**plural**, comma-joined — differs from :meth:`get_session`'s singular
        ``session_id``).  Like :meth:`quit_session`, this never raises: teardown
        must not mask the test result.  Returns ``True`` when the call returned
        a status below 400.
        """
        if isinstance(session_ids, str):
            ids = session_ids
        else:
            ids = ",".join(str(sid) for sid in session_ids)
        kwparams: dict[str, Any] = {"session_ids": ids}
        if force_quit:
            kwparams["force_quit"] = True
        if suspend:
            kwparams["suspend"] = True
        try:
            resp = self._client.post(
                "/api/stop_session",
                json={"method": "stop_session", "kwparams": kwparams},
            )
            return resp.status_code < 400
        except Exception:
            return False

    def wait_for_active(
        self,
        session_id: str,
        *,
        username: str | None = None,
        timeout: float,
        poll_interval: float = 2.0,
    ) -> str:
        """Poll ``get_session`` until the session is active; return its state.

        Returns ``"running"`` (:data:`SESSION_ACTIVE_STATE`) once the session
        reaches it.  Fails fast by raising :class:`WorkbenchSessionError` if the
        session hits a terminal failure state
        (:data:`SESSION_TERMINAL_FAILURE_STATES`) so a dead session does not
        wait out the full *timeout*, and raises :class:`WorkbenchSessionError`
        on timeout naming the last-observed state.

        The docs recommend the ``timestamp`` long-poll on ``get_session``; a
        simple bounded poll (``time.monotonic`` deadline + ``time.sleep``) is
        sufficient here and matches the repo's UI-poll style.
        """
        deadline = time.monotonic() + timeout
        last_state = "unknown"
        while True:
            result = self.get_session(
                session_id, username=username, fields=["id", "activity_state", "running"]
            )
            last_state = _session_activity_state(result) or last_state
            if last_state == SESSION_ACTIVE_STATE:
                return last_state
            if last_state in SESSION_TERMINAL_FAILURE_STATES:
                raise WorkbenchSessionError(
                    f"Workbench session {session_id!r} reached terminal state "
                    f"{last_state!r} instead of {SESSION_ACTIVE_STATE!r}. The "
                    "deployment could not launch the session — verify the launcher, "
                    "the session image, and available CPU/memory/quota."
                )
            if time.monotonic() >= deadline:
                raise WorkbenchSessionError(
                    f"Workbench session {session_id!r} did not reach "
                    f"{SESSION_ACTIVE_STATE!r} within {timeout:.0f}s "
                    f"(last observed state: {last_state!r})."
                )
            time.sleep(poll_interval)

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

    def count_vip_sessions(self) -> int:
        """Count VIP-named sessions currently listed, or ``-1`` if undeterminable.

        Returns the number of sessions matching :func:`is_vip_session`
        (``0`` when the list genuinely holds none), or ``-1`` when the count
        cannot be determined — a transport error, a non-200, or a body that is
        not a JSON ``list`` (e.g. a ``200`` HTML/SPA fallback or an error
        object).  Callers use the ``-1`` "unknown" signal to escalate cleanup
        defensively rather than mistake an unparseable response for "clean"
        (which would suppress the UI sweep and re-orphan sessions — issue #467).
        Never raises.
        """
        try:
            resp = self._client.get("/api/sessions")
            if resp.status_code != 200:
                return -1
            sessions = resp.json()
        except Exception:
            return -1
        if not isinstance(sessions, list):
            return -1
        return sum(
            1 for s in sessions if isinstance(s, dict) and is_vip_session(str(s.get("label") or ""))
        )

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
