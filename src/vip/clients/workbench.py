"""Lightweight Posit Workbench API client for VIP tests.

Uses plain ``httpx`` for loose coupling.  Workbench exposes fewer public
APIs than Connect, so many checks are done via the web UI with Playwright.
The documented Workbench API (``POST /api/<method>``, authenticated with an
``Authorization: Bearer <token>`` API token) covers launching, inspecting and
stopping sessions without a browser.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from vip.clients.base import BaseClient
from vip.errors import ProductUnreachableError
from vip.proxy import ProxyConfig

logger = logging.getLogger(__name__)

_VIP_SESSION_PREFIXES = ("VIP ", "_vip_")

# VIP session names embed the xdist worker that created the session, so a sweep
# can tell its own sessions apart from a sibling worker's:
#   "VIP test_git_ops.py - gw1-1785380284140718000"  (unique_session_name)
#   "_vip_cap_gw1_1785380282_Small_0"                (capacity scenarios)
#   "_vip_k8s_gw2_1785380282_fill_0"                 (k8s capacity scenarios)
# Serial runs use the literal worker id "main".
#
# The second pattern is deliberately generic over the ``<kind>`` segment rather
# than listing "cap" and "k8s": a new `_vip_<kind>_` scheme then stays
# attributable by construction. A scheme that forgets the worker segment is
# unowned, and unowned means no in-run sweep will ever clean it up -- which is
# how `_vip_k8s_` sessions started leaking when worker scoping first landed.
_VIP_OWNER_PATTERNS = (
    re.compile(r"^VIP .+ - (?P<owner>main|gw\d+)-\d+$"),
    re.compile(r"^_vip_[a-z0-9]+_(?P<owner>main|gw\d+)_"),
)


# Workbench API ``activity_state`` values. "running" is ready; "failed" and
# "killed" are exits a just-launched session never recovers from, so a waiter
# fails fast on them instead of waiting out its whole timeout.
SESSION_RUNNING_STATE = "running"
SESSION_FAILED_STATES = ("failed", "killed")
# Exits after which a session no longer needs stopping.
_SESSION_GONE_STATES = ("finished", "failed", "killed")

# The exact ``workbench`` kwparam values ``launch_session`` accepts. Case and
# spacing matter, so these are never normalized.
WORKBENCH_API_IDES = ("RStudio", "VS Code", "JupyterLab", "Positron")

_FALLBACK_CLUSTER = "Local"


# Appended to 401/403/404 errors: the usual reasons a configured token can't be used.
_TOKEN_REFUSED_HINT = (
    ". Check that VIP_WORKBENCH_API_KEY is a super-admin token from "
    "`rstudio-server generate-api-token`, that rserver.conf sets workbench-api-enabled=1 "
    "and workbench-api-super-admin-enabled=1, and that the deployment is Enhanced or Advanced."
)


class WorkbenchApiError(ProductUnreachableError):
    """The Workbench API refused or failed a call.

    ``status_code`` is set for an HTTP-level failure (401 is a rejected token);
    ``code`` is set for a processing error the API reports inside an HTTP 200
    ``{"error": {"code", "message"}}`` envelope.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, code: int | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class WorkbenchSessionError(ProductUnreachableError):
    """A launched session failed, or never reached the running state in time."""


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


def is_ide_offered(compute_envs: dict[str, Any], workbench: str) -> bool:
    """Return True if a ``get_compute_envs`` result offers *workbench* for launch.

    The IDE must appear in ``result.workbenches`` and not be flagged unavailable
    (``lang.available`` false means the IDE's runtime is not installed).
    """
    entry = (compute_envs.get("workbenches") or {}).get(workbench)
    if not isinstance(entry, dict):
        return False
    lang = entry.get("lang")
    return not (isinstance(lang, dict) and lang.get("available") is False)


def default_launch_parameters(
    compute_envs: dict[str, Any], workbench: str, name: str
) -> dict[str, Any]:
    """Build the ``launch_parameters`` a launch needs when launcher sessions are enabled.

    The cluster is the IDE's ``default_cluster`` when that names a real cluster,
    else the first cluster that supports interactive sessions for the IDE, else
    ``"Local"``.  When that cluster defines resource profiles the launcher rejects
    a launch that names none, so the profile called ``default`` (else the first)
    is sent as ``resource_profile``.  ``name`` and ``cluster`` are the documented
    minimum and are harmless on a deployment that does not use the launcher.
    """
    clusters = [c for c in compute_envs.get("clusters") or [] if isinstance(c, dict)]
    names = [str(c.get("name")) for c in clusters if c.get("name")]
    entry = (compute_envs.get("workbenches") or {}).get(workbench)
    default = entry.get("default_cluster") if isinstance(entry, dict) else None
    chosen: dict[str, Any] | None = None
    if default and (not names or default in names):
        cluster = str(default)
        chosen = next((c for c in clusters if c.get("name") == default), None)
    else:
        chosen = next(
            (
                c
                for c in clusters
                if c.get("name")
                and (c.get("workbenches") or {})
                .get(workbench, {})
                .get("supports_interactive_sessions")
            ),
            None,
        )
        cluster = str(chosen["name"]) if chosen else str(default or _FALLBACK_CLUSTER)
    params: dict[str, Any] = {"name": name, "cluster": cluster}
    profiles = [p["name"] for p in (chosen or {}).get("resourceProfiles") or [] if p.get("name")]
    if profiles:
        params["resource_profile"] = "default" if "default" in profiles else profiles[0]
    return params


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
        proxy: ProxyConfig | None = None,
    ) -> None:
        super().__init__(
            base_url,
            auth_header_value=f"Bearer {api_key}" if api_key else "",
            timeout=timeout,
            insecure=insecure,
            ca_bundle=ca_bundle,
            auth=auth,
            cookies=cookies,
            proxy=proxy,
        )

    # -- Health / info ------------------------------------------------------

    def health(self) -> int:
        """Return the HTTP status code of the health endpoint."""
        resp = self._client.get("/health-check")
        return resp.status_code

    # Note: Workbench has no unauthenticated server-info/version endpoint. The
    # deployed version is read from the authenticated homepage footer instead
    # (see ``vip_tests/workbench/test_version.py`` and
    # ``pages/homepage.parse_workbench_version``). The documented REST API's
    # ``/api/version`` is tier-gated (Enhanced/Advanced) and disabled by
    # default, so :meth:`get_version` is only for runs that carry an API token.

    # -- Workbench API (token-authenticated) ---------------------------------

    def _call(
        self,
        method: str,
        kwparams: dict[str, Any] | None = None,
        *,
        get: bool = False,
        bare_ok: bool = False,
    ) -> Any:
        """Call ``/api/<method>`` and return the ``result`` payload.

        POSTs ``{"method", "kwparams"}`` (or GETs, for the parameterless methods
        the API allows that for).  With *bare_ok*, a success body that has no
        ``result`` wrapper is returned as is.  Raises :class:`WorkbenchApiError` on a non-2xx
        status, on a body that is not a JSON object, and on the HTTP-200
        ``{"error": {...}}`` envelope the API uses for processing errors.
        """
        body: dict[str, Any] = {"method": method}
        if kwparams:
            body["kwparams"] = kwparams
        try:
            if get:
                resp = self._client.get(f"/api/{method}")
            else:
                resp = self._client.post(f"/api/{method}", json=body)
        except httpx.HTTPError as exc:
            raise WorkbenchApiError(f"Workbench API {method} could not be reached: {exc}") from exc
        if resp.status_code >= 400:
            hint = _TOKEN_REFUSED_HINT if resp.status_code in (401, 403, 404) else ""
            raise WorkbenchApiError(
                f"Workbench API {method} returned HTTP {resp.status_code}{hint}",
                status_code=resp.status_code,
            )
        if bare_ok and not resp.content.strip():
            return {}
        try:
            payload = resp.json()
        except ValueError as exc:
            raise WorkbenchApiError(
                f"Workbench API {method} returned a non-JSON body: {resp.text[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise WorkbenchApiError(f"Workbench API {method} returned a non-object body")
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            raise WorkbenchApiError(
                f"Workbench API {method} failed (code {code}): {error.get('message')}",
                code=code if isinstance(code, int) else None,
            )
        if "result" in payload:
            return payload["result"]
        if bare_ok:
            return payload
        raise WorkbenchApiError(f"Workbench API {method} returned no result")

    def get_version(self) -> dict[str, Any]:
        """Return ``GET /api/version``'s ``version`` and ``features``.

        A cheap call that proves the API is enabled and the token is accepted.
        A live server answers with the object itself rather than a ``result``
        wrapper, so both are accepted.
        """
        return self._call("version", get=True, bare_ok=True)

    def get_compute_envs(self, *, user: str | None = None) -> dict[str, Any]:
        """Return ``result`` of ``get_compute_envs``: ``clusters`` and ``workbenches``.

        *user* (admin or super-admin token) reads the environments that user sees.
        """
        return self._call("get_compute_envs", {"user": user} if user else None)

    def get_launch_compute_envs(self, user: str) -> dict[str, Any]:
        """Return the compute environments *user* would launch into.

        Asks for *user*'s environments, which a super-admin token may do and
        which carries that user's resource profiles.  A token that may not (a
        user token, for one) gets its own environments instead; a refused token
        (HTTP 401, 403 or 404) is not retried.
        """
        try:
            return self.get_compute_envs(user=user)
        except WorkbenchApiError as exc:
            if exc.status_code in (401, 403, 404):
                raise
            return self.get_compute_envs()

    def launch_session(
        self,
        workbench: str,
        *,
        username: str | None = None,
        name: str | None = None,
        launch_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Launch a session and return ``{"id", "url", "project_id"}``.

        *workbench* is one of :data:`WORKBENCH_API_IDES`.  A super-admin token may
        pass *username* to launch on that user's behalf.  *launch_parameters* is
        required when launcher sessions are enabled (see
        :func:`default_launch_parameters`).
        """
        kwparams: dict[str, Any] = {"workbench": workbench}
        if username:
            kwparams["username"] = username
        if name:
            kwparams["name"] = name
        if launch_parameters:
            kwparams["launch_parameters"] = launch_parameters
        return self._call("launch_session", kwparams)

    def get_session(
        self,
        session_id: str | None = None,
        *,
        user: str | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return ``result`` of ``get_session``: ``{"sessions": [...], "timestamp": ...}``.

        The id kwparam is the singular ``session_id`` here but ``session_ids`` in
        :meth:`stop_session`; the API is inconsistent.  With no *user* the token
        owner's sessions are returned.
        """
        kwparams: dict[str, Any] = {}
        if session_id:
            kwparams["session_id"] = session_id
        if user:
            kwparams["user"] = user
        if fields:
            kwparams["fields"] = fields
        return self._call("get_session", kwparams)

    def stop_session(
        self,
        session_ids: str | Iterable[str],
        *,
        force_quit: bool = False,
        suspend: bool = False,
    ) -> None:
        """Stop (or suspend) sessions.

        Raises :class:`WorkbenchApiError` carrying Workbench's own reply when the
        API refuses the call.  Teardown should use :meth:`try_stop_session`.
        """
        ids = session_ids if isinstance(session_ids, str) else ",".join(session_ids)
        kwparams: dict[str, Any] = {"session_ids": ids}
        if force_quit:
            kwparams["force_quit"] = True
        if suspend:
            kwparams["suspend"] = True
        # A successful stop answers with an empty result, which may be no body at all.
        self._call("stop_session", kwparams, bare_ok=True)

    def try_stop_session(
        self,
        session_ids: str | Iterable[str],
        *,
        force_quit: bool = False,
        suspend: bool = False,
    ) -> bool:
        """Best-effort :meth:`stop_session` for teardown; never raises.

        Returns True when the API accepted the call, and logs the refusal
        otherwise so a failed cleanup is visible without turning a run red.
        """
        try:
            self.stop_session(session_ids, force_quit=force_quit, suspend=suspend)
        except ProductUnreachableError as exc:
            logger.warning("Workbench stop_session for %s failed: %s", session_ids, exc)
            return False
        return True

    def wait_for_session_running(
        self,
        session_id: str,
        *,
        user: str | None = None,
        timeout: float,
        poll_interval: float = 2.0,
    ) -> None:
        """Poll ``get_session`` until *session_id* is ``running``.

        Raises :class:`WorkbenchSessionError` as soon as the session reports a
        failed or killed state, or when *timeout* seconds pass first; both name
        the last state seen.
        """
        deadline = time.monotonic() + timeout
        last_state = "not listed"
        while True:
            result = self.get_session(
                session_id, user=user, fields=["id", "activity_state", "label"]
            )
            sessions = result.get("sessions") if isinstance(result, dict) else None
            if not isinstance(sessions, list):
                raise WorkbenchApiError("Workbench API get_session returned no sessions list")
            for session in sessions:
                if isinstance(session, dict) and session.get("id") == session_id:
                    last_state = str(session.get("activity_state") or "unknown")
                    break
            if last_state == SESSION_RUNNING_STATE:
                return
            if last_state in SESSION_FAILED_STATES:
                raise WorkbenchSessionError(
                    f"Workbench session {session_id} ended as {last_state!r} instead of "
                    f"{SESSION_RUNNING_STATE!r}; check the launcher, session image and "
                    "available CPU and memory."
                )
            if time.monotonic() >= deadline:
                raise WorkbenchSessionError(
                    f"Workbench session {session_id} was not {SESSION_RUNNING_STATE!r} after "
                    f"{timeout:.0f}s (last state: {last_state!r})."
                )
            time.sleep(poll_interval)

    def wait_for_session_stopped(
        self,
        session_id: str,
        *,
        user: str | None = None,
        timeout: float,
        poll_interval: float = 2.0,
    ) -> None:
        """Poll ``get_session`` until *session_id* has left the active list or ended.

        ``get_session`` lists only active sessions, so a stopped session either
        disappears or reports an ended state.  Raises :class:`WorkbenchSessionError`
        naming the last state if it is still active after *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        while True:
            result = self.get_session(session_id, user=user, fields=["id", "activity_state"])
            sessions = result.get("sessions") if isinstance(result, dict) else None
            if not isinstance(sessions, list):
                raise WorkbenchApiError("Workbench API get_session returned no sessions list")
            match = next(
                (s for s in sessions if isinstance(s, dict) and s.get("id") == session_id), None
            )
            state = str(match.get("activity_state") or "unknown") if match else None
            if state is None or state in _SESSION_GONE_STATES:
                return
            if time.monotonic() >= deadline:
                raise WorkbenchSessionError(
                    f"Workbench session {session_id} was still {state!r} {timeout:.0f}s after "
                    "stop_session was accepted."
                )
            time.sleep(poll_interval)

    def vip_sessions_via_api(self, user: str, *, owner: str | None = None) -> list[dict[str, Any]]:
        """List *user*'s live VIP-named sessions through the token API.

        *owner* scopes the list to one xdist worker, as in :meth:`quit_vip_sessions`.
        Sessions that already exited are left out.  Raises
        :class:`WorkbenchApiError` when the listing fails.
        """
        result = self.get_session(user=user, fields=["id", "label", "activity_state"])
        sessions = result.get("sessions") if isinstance(result, dict) else None
        if not isinstance(sessions, list):
            raise WorkbenchApiError("Workbench API get_session returned no sessions list")
        return [
            s
            for s in sessions
            if self._is_target(s, owner) and s.get("activity_state") not in _SESSION_GONE_STATES
        ]

    def quit_vip_sessions_via_api(
        self,
        user: str,
        *,
        owner: str | None = None,
        retries: int = 2,
        settle_seconds: float = 0.5,
    ) -> int:
        """Force-stop *user*'s VIP-named sessions with the API token; return how many.

        The token counterpart of :meth:`quit_vip_sessions` for runs with no browser
        cookies (``--api-auth``).  *owner* has the same meaning: pass the worker id
        from an in-run sweep, ``None`` for ``vip cleanup``.  Re-lists after each
        stop and logs a WARNING naming any session that survives every retry.
        Raises :class:`WorkbenchApiError` if the listing fails.
        """
        stopped: set[str] = set()
        remaining: list[dict[str, Any]] = []
        for attempt in range(retries):
            remaining = self.vip_sessions_via_api(user, owner=owner)
            if not remaining:
                return len(stopped)
            ids = [str(s["id"]) for s in remaining if s.get("id")]
            if ids and self.try_stop_session(ids, force_quit=True):
                stopped.update(ids)
            if attempt < retries - 1:
                time.sleep(settle_seconds)
        remaining = self.vip_sessions_via_api(user, owner=owner)
        if remaining:
            logger.warning(
                "quit_vip_sessions_via_api: %d VIP-named Workbench session(s) still present "
                "after cleanup: %s",
                len(remaining),
                ", ".join(f"{s.get('label')!r} (id={s.get('id')})" for s in remaining),
            )
        return len(stopped)

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
        except Exception:  # noqa: BLE001
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
        """Count VIP-named sessions currently listed.

        With *owner* set, counts only that xdist worker's own sessions, so a
        per-test cleanup does not read a sibling worker's live session as
        "leftovers" and escalate to a sweep that would quit it.

        Returns the number of sessions matching :func:`is_vip_session_for_owner`
        (``0`` when the list genuinely holds none).  Raises
        :class:`ProductUnreachableError` when the count cannot be determined —
        a transport error, a non-200, or a body that is not a JSON ``list``
        (e.g. a ``200`` HTML/SPA fallback or an error object) — so callers
        cannot mistake an unparseable response for "clean" (which would
        suppress the UI sweep and re-orphan sessions — issue #467).
        """
        try:
            resp = self._client.get("/api/sessions")
            if resp.status_code != 200:
                raise ProductUnreachableError(f"GET /api/sessions returned {resp.status_code}")
            sessions = resp.json()
        except ProductUnreachableError:
            raise
        except Exception as exc:
            raise ProductUnreachableError(f"could not list Workbench sessions: {exc}") from exc
        if not isinstance(sessions, list):
            raise ProductUnreachableError("GET /api/sessions did not return a JSON list")
        return sum(1 for s in sessions if self._is_target(s, owner))

    def sessions_api_reachable(self) -> bool:
        """Return True only if ``/api/sessions`` returns a usable session list.

        The API-based cleanup (:meth:`list_sessions` / :meth:`quit_vip_sessions`)
        works only when this endpoint responds ``200`` with a JSON **array**.
        Some deployments instead 404 (SPA fallback), serve ``200`` HTML, or
        redirect to login (``302``) — all status codes that are not a usable
        list.  Returning True for those would wrongly suppress the UI-driven
        cleanup fallback and orphan VIP sessions, so we require a ``200`` whose
        body parses as a ``list``.  Raises :class:`ProductUnreachableError` on
        any transport exception, so callers cannot mistake "the request itself
        failed" for a well-formed "not a list" response.
        """
        try:
            resp = self._client.get("/api/sessions")
            if resp.status_code != 200:
                return False
            return isinstance(resp.json(), list)
        except Exception as exc:
            raise ProductUnreachableError(f"could not reach the sessions API: {exc}") from exc

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
            except Exception:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
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
            try:
                self._warn_if_vip_sessions_remain(owner)
            except ProductUnreachableError:
                # Best-effort warning only — the sweep above already gave up
                # on this listing being reachable; don't fail the sweep over
                # a diagnostic log message it couldn't produce.
                pass
        return len(quit_ids)

    def _warn_if_vip_sessions_remain(self, owner: str | None = None) -> None:
        """Log a WARNING naming any VIP session still listed right now.

        Called after :meth:`quit_vip_sessions` exhausts its retries with VIP
        sessions still present on the last listing, so a session that quietly
        survived every quit attempt is surfaced loudly instead of the caller
        just getting back a count.  Raises :class:`ProductUnreachableError` if
        the listing call itself fails; :meth:`quit_vip_sessions` treats that as
        best-effort and swallows it rather than failing the sweep.
        """
        try:
            resp = self._client.get("/api/sessions")
            if resp.status_code != 200:
                raise ProductUnreachableError(f"GET /api/sessions returned {resp.status_code}")
            sessions = resp.json()
        except ProductUnreachableError:
            raise
        except Exception as exc:
            raise ProductUnreachableError(f"could not list Workbench sessions: {exc}") from exc
        if not isinstance(sessions, list):
            raise ProductUnreachableError("GET /api/sessions did not return a JSON list")
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
