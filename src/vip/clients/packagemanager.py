"""Lightweight Posit Package Manager API client for VIP tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from vip.clients.base import BaseClient


class PackageManagerClient(BaseClient):
    """Minimal Package Manager HTTP wrapper."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        *,
        timeout: float | None = None,
        insecure: bool = False,
        ca_bundle: Path | None = None,
        auth: httpx.Auth | None = None,
    ) -> None:
        super().__init__(
            base_url,
            auth_header_value=f"Bearer {token}" if token else "",
            timeout=timeout,
            insecure=insecure,
            ca_bundle=ca_bundle,
            auth=auth,
        )

    # -- Health / status ----------------------------------------------------

    def health(self) -> int:
        """Return the HTTP status code for the status endpoint."""
        resp = self._client.get("/__api__/status")
        return resp.status_code

    # -- Repos --------------------------------------------------------------

    def list_repos(self) -> list[dict[str, Any]]:
        """List configured repositories."""
        resp = self._client.get("/__api__/repos")
        resp.raise_for_status()
        return resp.json()

    def list_authenticated_repos(self) -> list[dict[str, Any]]:
        """List repositories with the ``auth`` flag set on the server.

        Authenticated repos require a valid token to download package content;
        see https://docs.posit.co/rspm/admin/repositories.html#authenticated-repos.
        """
        return [r for r in self.list_repos() if r.get("auth") is True]

    def status(self) -> dict[str, Any]:
        """Return the parsed JSON body from the status endpoint."""
        resp = self._client.get("/__api__/status")
        resp.raise_for_status()
        return resp.json()

    # -- CRAN ---------------------------------------------------------------

    def cran_package_available(self, repo_name: str, package: str) -> bool:
        """Check whether a CRAN package is available in a repo."""
        resp = self._client.get(f"/{repo_name}/latest/src/contrib/PACKAGES")
        if resp.status_code != 200:
            return False
        return package in resp.text

    # -- Bioconductor -------------------------------------------------------

    def bioconductor_package_available(self, repo_name: str, package: str) -> bool:
        """Check whether a Bioconductor package is available in a repo.

        Queries the internal package API with the latest Bioconductor version
        obtained from the status endpoint.
        """
        status_resp = self._client.get("/__api__/status")
        if status_resp.status_code != 200:
            return False
        bioc_versions = status_resp.json().get("bioc_versions", [])
        if not bioc_versions:
            return False
        bioc_version = bioc_versions[0]["bioc_version"]
        resp = self._client.get(
            f"/__api__/repos/{repo_name}/packages",
            params={"bioc_version": bioc_version, "name": package},
        )
        if resp.status_code != 200:
            return False
        return any(p.get("name") == package for p in resp.json())

    # -- OpenVSX (VSX) ------------------------------------------------------

    def openvsx_extension_available(self, repo_name: str, extension: str) -> bool:
        """Check whether an OpenVSX extension is available in a repo.

        *extension* uses the ``namespace.name`` format, e.g. ``"golang.Go"``.
        """
        resp = self._client.get(f"/__api__/repos/{repo_name}/packages/{extension}")
        return resp.status_code == 200

    # -- PyPI ---------------------------------------------------------------

    def pypi_package_available(self, repo_name: str, package: str) -> bool:
        """Check whether a PyPI package is available in a repo."""
        resp = self._client.get(f"/{repo_name}/latest/simple/{package}/")
        return resp.status_code == 200
