"""Lightweight Posit Connect API client for VIP tests.

This client uses plain ``httpx`` rather than a product-specific SDK to
avoid tight coupling to a particular release of the Connect client library.
"""

from __future__ import annotations

from typing import Any

import httpx

_VIP_CONTENT_TAG = "_vip_test"


class ConnectClient:
    """Minimal Connect API wrapper."""

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self.base_url}/__api__",
            headers={"Authorization": f"Key {api_key}"},
            timeout=timeout,
        )

    # -- Server info --------------------------------------------------------

    def server_settings(self) -> dict[str, Any]:
        resp = self._client.get("/server_settings")
        resp.raise_for_status()
        return resp.json()

    def server_status(self) -> int:
        """Return the HTTP status code for the server health endpoint."""
        resp = self._client.get("/v1/server_settings")
        return resp.status_code

    # -- Users --------------------------------------------------------------

    def current_user(self) -> dict[str, Any]:
        resp = self._client.get("/v1/user")
        resp.raise_for_status()
        return resp.json()

    # -- Content ------------------------------------------------------------

    def list_content(self) -> list[dict[str, Any]]:
        resp = self._client.get("/v1/content")
        resp.raise_for_status()
        return resp.json()

    def create_content(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Create a new content item tagged for VIP cleanup."""
        payload: dict[str, Any] = {"name": name, **kwargs}
        resp = self._client.post("/v1/content", json=payload)
        resp.raise_for_status()
        content = resp.json()
        # Tag the content so we can identify and clean it up later.
        self._tag_content(content["guid"], _VIP_CONTENT_TAG)
        return content

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
        resp = self._client.get(f"/v1/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

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

    def cleanup_vip_content(self) -> int:
        """Delete all content items tagged as VIP test content.

        Returns the number of items deleted.
        """
        deleted = 0
        try:
            resp = self._client.get("/v1/tags", params={"name": _VIP_CONTENT_TAG})
            resp.raise_for_status()
            tags = resp.json()
            if not tags:
                return 0
            tag_id = tags[0]["id"]
            resp = self._client.get(f"/v1/tags/{tag_id}/content")
            resp.raise_for_status()
            for item in resp.json():
                self.delete_content(item["guid"])
                deleted += 1
        except Exception:
            pass
        return deleted

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

    # -- Email --------------------------------------------------------------

    def send_test_email(self, to: str) -> dict[str, Any]:
        resp = self._client.post("/v1/tasks/send-test-email", json={"to": to})
        resp.raise_for_status()
        return resp.json()

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()
