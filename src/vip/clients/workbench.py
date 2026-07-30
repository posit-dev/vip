"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from vip.clients.base import BaseClient

logger = logging.getLogger(__name__)

_VIP_SESSION_PREFIXES = ("VIP ", "_vip_")

# Both VIP session-naming schemes embed the xdist worker that created the
# session, so a sweep can tell its own sessions apart from a sibling worker's:
#   "VIP test_git_ops.py - gw1-1785380284140718000"  (unique_session_name)
#   "_vip_cap_gw1_1785380282_Small_0"                (capacity scenarios)
# Serial runs use the literal worker id "main".
_VIP_OWNER_PATTERNS = (
    re.compile(r"^VIP .+ - (?P<owner>main|gw\d+)-\d+$"),
    re.compile(r"^_vip_cap_(?P<owner>main|gw\d+)_"),
)


def is_vip_session(label: str) -> bool:
    """Return True if *label* matches a VIP-created session naming pattern.

    VIP names sessions either ``"VIP <file> - <worker>-<ns>"`` (most tests,
    via ``unique_session_name``) or ``"_vip_cap_<worker>_<ts>_..."`` (capacity
    tests).
    """
    return any(label.startswith(prefix) for prefix in _VIP_SESSION_PREFIXES)


def session_owner(label: str) -> str | None:
    """Return the xdist worker id encoded in *label*, or ``None``.

    ``None`` means "not attributable": a real user's session, or a VIP session
    named by an older VIP release whose scheme carried no worker segment.
    Callers must treat an unattributable session as *not theirs* during a run,
    or they reintroduce the cross-worker kill this exists to prevent.
    """
    for pattern in _VIP_OWNER_PATTERNS:
        match = pattern.match(label)
        if match:
            return match.group("owner")
    return None


def is_vip_session_for_owner(label: str, owner: str | None) -> bool:
    """Return True if *label* is a VIP session this caller may quit.

    With *owner* ``None`` (``vip cleanup``, or the end-of-run safety net) every
    VIP-named session matches -- there is no concurrent worker left to protect.
    With an *owner* set, only that worker's own sessions match, so a per-test
    sweep cannot quit a session another xdist worker is still driving.
    """
    if not is_vip_session(label):
        return False
    if owner is None:
        return True
    return session_owner(label) == owner


def jupyterlab_app_base(page_url: str) -> str:
    """Return the JupyterLab app-root URL from a session page URL.

    A Workbench JupyterLab session is served under a per-session proxy prefix,
    e.g. ``https://wb.example.com/s/abc123/lab/tree/Untitled.ipynb``.  The
    JupyterLab server (and its ``/api/contents`` REST surface) is mounted at the
    segment ending in ``/lab`` — everything *before* ``/lab`` is the app base
    (``https://wb.example.com/s/abc123``).  The returned value has no trailing
    slash.  If the URL has no ``/lab`` segment (unexpected), the input is
    returned with any query/fragment and trailing slash stripped, so callers
    still get a usable base rather than raising mid-teardown.
    """
    # Drop query string and fragment first — the contents API path is built
    # fresh, so anything after ``?``/``#`` is irrelevant and would corrupt the base.
    core = page_url.split("?", 1)[0].split("#", 1)[0]
    marker = "/lab"
    idx = core.find(marker)
    if idx != -1:
        return core[:idx].rstrip("/")
    return core.rstrip("/")


def jupyterlab_contents_delete_url(page_url: str, notebook_name: str) -> str:
    """Build the ``DELETE /api/contents/<notebook>`` URL for a JupyterLab session.

    *page_url* is the current session page URL (see :func:`jupyterlab_app_base`);
    *notebook_name* is the notebook's filename as shown on its dock tab (e.g.
    ``"Untitled.ipynb"``).  The name is URL-quoted so spaces/special characters
    in a renamed notebook do not break the path.  Any leading slashes on the
    name are stripped so the result is always ``<app_base>/api/contents/<name>``.
    """
    from urllib.parse import quote

    base = jupyterlab_app_base(page_url)
    clean = notebook_name.strip().lstrip("/")
    return f"{base}/api/contents/{quote(clean)}"


def jupyterlab_xsrf_headers(cookies: dict[str, str]) -> dict[str, str]:
    """Return the XSRF header JupyterLab requires for mutating contents-API calls.

    JupyterLab protects non-GET ``/api`` requests with a double-submit token:
    the ``_xsrf`` cookie value must be echoed back in the ``X-XSRFToken`` header.
    Returns ``{"X-XSRFToken": <value>}`` when the cookie is present, or an empty
    dict when it is absent (older/token-auth deployments) so the caller can still
    attempt the request without sending a bogus header.
    """
    token = cookies.get("_xsrf")
    return {"X-XSRFToken": token} if token else {}


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

    def delete_jupyter_notebook(
        self, page_url: str, notebook_name: str, cookies: dict[str, str]
    ) -> bool:
        """Delete a notebook file from a live JupyterLab session's contents API.

        Sends ``DELETE <app_base>/api/contents/<notebook_name>`` authenticated
        with the browser session *cookies* and the ``X-XSRFToken`` header
        JupyterLab requires for mutating calls (see
        :func:`jupyterlab_contents_delete_url` / :func:`jupyterlab_xsrf_headers`).

        This exists so a test that creates a notebook can remove it *before the
        session is quit* — the contents API only exists while the session is
        alive — so JupyterLab's layout-restorer stops reopening stale
        ``Untitled*.ipynb`` tabs (and eagerly starting their kernels) on every
        subsequent session launch, which widens the launch/exec interaction race.

        Returns True when the server accepts the delete (HTTP < 400, including
        the ``204`` success and a ``404`` for an already-absent file), False on
        any other status or transport error.  Never raises — teardown cleanup is
        a best-effort safety net, not an assertion.
        """
        url = jupyterlab_contents_delete_url(page_url, notebook_name)
        headers = jupyterlab_xsrf_headers(cookies)
        try:
            # Set cookies on the client instance (per-request cookies= is
            # deprecated in httpx and its persistence semantics are ambiguous).
            self._client.cookies.update(cookies)
            resp = self._client.request("DELETE", url, headers=headers)
        except Exception:
            return False
        # 404 → already gone, treat as success (idempotent teardown).
        return resp.status_code < 400 or resp.status_code == 404

    def list_sessions(self) -> list[dict[str, Any]]:
        """List active sessions for the authenticated user."""
        resp = self._client.get("/api/sessions")
        if resp.status_code == 200:
            return resp.json()
        return []

    @staticmethod
    def _is_target(session: Any, owner: str | None) -> bool:
        """Return True if *session* is a VIP session this caller may act on.

        Shared by the count and quit paths so both agree on what "mine" means
        (see :func:`is_vip_session_for_owner`).  Coerces the label to ``str`` so
        a null or non-string label never raises.
        """
        if not isinstance(session, dict):
            return False
        return is_vip_session_for_owner(str(session.get("label") or ""), owner)

    def count_vip_sessions(self, *, owner: str | None = None) -> int:
        """Count VIP-named sessions currently listed, or ``-1`` if undeterminable.

        With *owner* set, counts only that xdist worker's own sessions, so a
        per-test cleanup does not read a sibling worker's live session as
        "leftovers" and escalate to a sweep that would quit it.

        Returns the number of sessions matching :func:`is_vip_session_for_owner`
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
        return sum(1 for s in sessions if self._is_target(s, owner))

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

    def quit_vip_sessions(
        self, *, retries: int = 2, settle_seconds: float = 0.5, owner: str | None = None
    ) -> int:
        """Force-quit VIP-named sessions reachable by this client.

        *owner* scopes the sweep to one xdist worker's own sessions.  Leave it
        ``None`` for a global sweep (``vip cleanup``, or the end-of-run safety
        net); pass the current worker id from a per-test cleanup, or the sweep
        will quit sessions a sibling worker is still driving mid-test.

        Lists sessions and quits only those matching :func:`is_vip_session_for_owner`
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
            targets = [s for s in sessions if self._is_target(s, owner)]
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
            self._warn_if_vip_sessions_remain(owner)
        return len(quit_ids)

    def _warn_if_vip_sessions_remain(self, owner: str | None = None) -> None:
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
        remaining = [s for s in sessions if self._is_target(s, owner)]
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
