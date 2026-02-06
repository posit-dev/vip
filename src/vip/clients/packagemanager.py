"""Lightweight Posit Package Manager API client for VIP tests."""

from __future__ import annotations

from typing import Any

import httpx


class PackageManagerClient:
    """Minimal Package Manager HTTP wrapper."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- Health / status ----------------------------------------------------

    def status(self) -> int:
        """Return the HTTP status code for the status endpoint."""
        resp = self._client.get("/__api__/status")
        return resp.status_code

    # -- Repos --------------------------------------------------------------

    def list_repos(self) -> list[dict[str, Any]]:
        """List configured repositories."""
        resp = self._client.get("/__api__/repos")
        resp.raise_for_status()
        return resp.json()

    def get_repo(self, repo_id: int | str) -> dict[str, Any]:
        resp = self._client.get(f"/__api__/repos/{repo_id}")
        resp.raise_for_status()
        return resp.json()

    # -- CRAN ---------------------------------------------------------------

    def cran_package_available(self, repo_name: str, package: str) -> bool:
        """Check whether a CRAN package is available in a repo."""
        resp = self._client.get(f"/{repo_name}/latest/src/contrib/PACKAGES")
        if resp.status_code != 200:
            return False
        return package in resp.text

    # -- PyPI ---------------------------------------------------------------

    def pypi_package_available(self, repo_name: str, package: str) -> bool:
        """Check whether a PyPI package is available in a repo."""
        resp = self._client.get(f"/{repo_name}/latest/simple/{package}/")
        return resp.status_code == 200

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()
