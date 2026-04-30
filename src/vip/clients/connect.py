"""Lightweight Posit Connect API client for VIP tests.

This client uses plain ``httpx`` rather than a product-specific SDK to
avoid tight coupling to a particular release of the Connect client library.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from vip.clients.base import BaseClient

_VIP_CONTENT_TAG = "_vip_test"


def _normalized_port(scheme: str | None, port: int | None) -> int | None:
    """Return the effective TCP port for a URL, filling in defaults for http/https."""
    if port is not None:
        return port
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


class ConnectClient(BaseClient):
    """Minimal Connect API wrapper."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        insecure: bool = False,
        ca_bundle: Path | None = None,
    ) -> None:
        api_key = (api_key or "").strip()
        super().__init__(
            base_url,
            auth_header_value=f"Key {api_key}" if api_key else "",
            api_prefix="/__api__",
            timeout=timeout,
            insecure=insecure,
            ca_bundle=ca_bundle,
        )
        # self._verify is set by BaseClient.__init__ and used by fetch_content.

    # -- Server info --------------------------------------------------------

    def server_settings(self) -> dict[str, Any]:
        resp = self._client.get("/server_settings")
        resp.raise_for_status()
        return resp.json()

    def health(self) -> int:
        """Return the HTTP status code for the server health endpoint."""
        resp = self._client.get("/server_settings")
        return resp.status_code

    # -- Users --------------------------------------------------------------

    def current_user(self) -> dict[str, Any]:
        resp = self._client.get("/v1/user")
        resp.raise_for_status()
        return resp.json()

    def list_users(self) -> list[dict[str, Any]]:
        resp = self._client.get("/v1/users")
        resp.raise_for_status()
        return resp.json().get("results", [])

    def list_groups(self) -> list[dict[str, Any]]:
        resp = self._client.get("/v1/groups")
        resp.raise_for_status()
        return resp.json().get("results", [])

    # -- Content ------------------------------------------------------------

    def create_content(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Create a new content item tagged for VIP cleanup.

        If content with the same name already exists (409 Conflict), the
        existing item is deleted and creation is retried.
        """
        payload: dict[str, Any] = {"name": name, **kwargs}
        resp = self._client.post("/v1/content", json=payload)
        if resp.status_code == 409:
            # Content with this name already exists — clean it up and retry.
            existing = self._find_content_by_name(name)
            if existing:
                self.delete_content(existing["guid"])
            resp = self._client.post("/v1/content", json=payload)
        resp.raise_for_status()
        content = resp.json()
        # Tag the content so we can identify and clean it up later.
        self._tag_content(content["guid"], _VIP_CONTENT_TAG)
        return content

    def _find_content_by_name(self, name: str) -> dict[str, Any] | None:
        """Return the first content item matching *name*, or ``None``."""
        resp = self._client.get("/v1/content", params={"name": name})
        if resp.status_code == 200:
            items = resp.json()
            return items[0] if items else None
        return None

    def delete_content(self, guid: str) -> None:
        resp = self._client.delete(f"/v1/content/{guid}")
        resp.raise_for_status()

    def get_content(self, guid: str) -> dict[str, Any]:
        resp = self._client.get(f"/v1/content/{guid}")
        resp.raise_for_status()
        return resp.json()

    def upload_bundle(self, guid: str, archive: bytes) -> dict[str, Any]:
        resp = self._client.post(
            f"/v1/content/{guid}/bundles",
            content=archive,
            headers={"Content-Type": "application/gzip"},
        )
        resp.raise_for_status()
        return resp.json()

    def deploy_bundle(self, guid: str, bundle_id: str) -> dict[str, Any]:
        resp = self._client.post(
            f"/v1/content/{guid}/deploy",
            json={"bundle_id": bundle_id},
        )
        resp.raise_for_status()
        return resp.json()

    def get_task(self, task_id: str) -> dict[str, Any]:
        resp = self._client.get(f"/v1/tasks/{task_id}", params={"first": 0, "wait": 1})
        resp.raise_for_status()
        return resp.json()

    def wait_for_task(self, task_id: str, timeout: float = 60.0) -> dict[str, Any]:
        """Poll a task until it finishes or timeout is reached.

        Polls ``get_task`` every 3 seconds, handling transient HTTP errors
        (ReadTimeout, 404/502/503/504) by retrying until the deadline.

        Returns the finished task dict.  If the deadline is reached without the
        task finishing, returns the most recent (unfinished) task dict so that
        callers can inspect the output and report an appropriate failure.
        """
        import time

        deadline = time.time() + timeout
        task: dict[str, Any] = {}
        while time.time() < deadline:
            try:
                task = self.get_task(task_id)
            except httpx.ReadTimeout:
                time.sleep(3)
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 502, 503, 504):
                    time.sleep(3)
                    continue
                raise
            if task.get("finished"):
                return task
            time.sleep(3)

        # Deadline reached — attempt one final fetch for up-to-date logs.
        for _ in range(3):
            try:
                task = self.get_task(task_id)
                break
            except httpx.ReadTimeout:
                time.sleep(3)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 502, 503, 504):
                    time.sleep(3)
                    continue
                raise

        return task

    def list_vip_content(self) -> list[dict[str, Any]]:
        """Return all content items tagged with the VIP test tag."""
        try:
            resp = self._client.get("/v1/tags", params={"name": _VIP_CONTENT_TAG})
            resp.raise_for_status()
            tags = resp.json()
            if not tags:
                return []
            tag_id = tags[0]["id"]
            resp = self._client.get(f"/v1/tags/{tag_id}/content")
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception:
            return []

    def cleanup_vip_content(self) -> int:
        """Delete all content tagged with the VIP test tag.

        Returns the number of items deleted.
        """
        items = self.list_vip_content()
        deleted = 0
        for item in items:
            guid = item.get("guid")
            if guid:
                try:
                    self.delete_content(guid)
                    deleted += 1
                except Exception:
                    pass
        return deleted

    # -- Tags ---------------------------------------------------------------

    def _tag_content(self, guid: str, tag_name: str) -> None:
        """Apply a tag to content for identification / cleanup."""
        # Best-effort: ignore errors so tests don't fail if tagging isn't
        # supported on this version.
        try:
            # Ensure the tag exists.
            resp = self._client.get("/v1/tags", params={"name": tag_name})
            resp.raise_for_status()
            tags = resp.json()
            if tags:
                tag_id = tags[0]["id"]
            else:
                resp = self._client.post("/v1/tags", json={"name": tag_name})
                resp.raise_for_status()
                tag_id = resp.json()["id"]
            self._client.post(f"/v1/content/{guid}/tags", json={"tag_id": tag_id})
        except Exception:
            pass

    # -- R / Python versions ------------------------------------------------

    def r_versions(self) -> list[str]:
        resp = self._client.get("/v1/server_settings/r")
        if resp.status_code == 200:
            installations = resp.json().get("installations", [])
            return [i["version"] for i in installations]
        return []

    def python_versions(self) -> list[str]:
        resp = self._client.get("/v1/server_settings/python")
        if resp.status_code == 200:
            installations = resp.json().get("installations", [])
            return [i["version"] for i in installations]
        return []

    def quarto_versions(self) -> list[str]:
        resp = self._client.get("/v1/server_settings/quarto")
        if resp.status_code == 200:
            installations = resp.json().get("installations", [])
            return [i.get("version", i.get("path", "")) for i in installations]
        return []

    # -- Git-backed publishing ----------------------------------------------

    def set_repository(
        self,
        guid: str,
        repo_url: str,
        branch: str = "main",
        directory: str = ".",
    ) -> dict[str, Any]:
        """Link a content item to a git repository via PUT."""
        payload: dict[str, Any] = {
            "repository": repo_url,
            "branch": branch,
            "directory": directory,
            "polling": False,
        }
        resp = self._client.put(f"/v1/content/{guid}/repository", json=payload)
        resp.raise_for_status()
        return resp.json()

    def deploy_from_repository(self, guid: str) -> dict[str, Any]:
        """Trigger a deployment from the linked git repository."""
        resp = self._client.post(f"/v1/content/{guid}/deploy", json={})
        resp.raise_for_status()
        return resp.json()

    # -- Content fetching (authenticated, redirect-safe) -----------------------

    def fetch_content(self, url: str, *, timeout: float = 30.0) -> httpx.Response:
        """Fetch a content URL with API-key auth, following only same-origin redirects.

        This avoids leaking the API key to external domains if Connect
        redirects to a CDN or OAuth provider.  A redirect is followed only
        when ALL of scheme, hostname, and effective port match the client's
        base URL, and the target scheme is http or https.
        """
        from urllib.parse import urljoin, urlparse

        origin = urlparse(self.base_url)
        origin_key = (origin.scheme, origin.hostname, _normalized_port(origin.scheme, origin.port))
        max_redirects = 10
        resp = httpx.get(
            url,
            headers={"Authorization": self._client.headers["Authorization"]},
            follow_redirects=False,
            timeout=timeout,
            verify=self._verify,
        )
        for _ in range(max_redirects):
            if not resp.is_redirect:
                break
            location = resp.headers.get("location", "")
            # Resolve relative Location values (e.g. "/content/{guid}/x.html")
            # against the current response URL before checking the origin.
            absolute_location = urljoin(str(resp.url), location)
            target = urlparse(absolute_location)
            # Reject non-http(s) schemes (e.g. file:, javascript:, ftp:).
            if target.scheme not in ("http", "https"):
                break
            # Only follow redirects to the exact same origin (scheme + host + port).
            target_key = (
                target.scheme,
                target.hostname,
                _normalized_port(target.scheme, target.port),
            )
            if target_key != origin_key:
                break
            resp = httpx.get(
                absolute_location,
                headers={"Authorization": self._client.headers["Authorization"]},
                follow_redirects=False,
                timeout=timeout,
                verify=self._verify,
            )
        return resp

    # -- System checks ------------------------------------------------------

    def list_system_checks(self) -> list[dict[str, Any]]:
        """Return a list of system check runs."""
        resp = self._client.get("/v1/system/checks")
        resp.raise_for_status()
        return resp.json()

    def run_system_check(self) -> dict[str, Any]:
        """Trigger a new system check run and return the run object."""
        resp = self._client.post("/v1/system/checks", json={})
        resp.raise_for_status()
        return resp.json()

    def get_system_check(self, check_id: str | int) -> dict[str, Any]:
        """Get the status of a system check run."""
        resp = self._client.get(f"/v1/system/checks/{check_id}")
        resp.raise_for_status()
        return resp.json()

    def get_system_check_results(self, check_id: str | int) -> dict[str, Any]:
        """Return the system check results as structured JSON."""
        resp = self._client.get(f"/v1/system/checks/{check_id}/results")
        resp.raise_for_status()
        return resp.json()

    def wait_for_system_check(self, check_id: str | int, timeout: float = 120.0) -> dict[str, Any]:
        """Poll a system check run until it completes or timeout is reached."""
        import time

        transient_status_codes = {404, 502, 503, 504}
        deadline = time.time() + timeout
        last_exception: Exception | None = None

        while time.time() < deadline:
            try:
                check = self.get_system_check(check_id)
            except httpx.ReadTimeout as exc:
                last_exception = exc
                time.sleep(3)
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in transient_status_codes:
                    raise
                last_exception = exc
                time.sleep(3)
                continue

            last_exception = None
            if check.get("status") == "done":
                return check
            time.sleep(3)

        for _ in range(3):
            try:
                return self.get_system_check(check_id)
            except httpx.ReadTimeout as exc:
                last_exception = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in transient_status_codes:
                    raise
                last_exception = exc
            time.sleep(1)

        if last_exception is not None:
            raise last_exception
        return self.get_system_check(check_id)

    # -- Email --------------------------------------------------------------

    def send_test_email(self, to: str) -> dict[str, Any]:
        resp = self._client.post("/v1/tasks/send-test-email", json={"to": to})
        resp.raise_for_status()
        return resp.json()
