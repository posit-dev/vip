"""Lightweight Posit Package Manager API client for VIP tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from vip.clients.base import BaseClient

# Binary-package probe tables.  PPM's macOS routing ties R version to arch:
# R 4.6+ -> sonoma-{arm64,x86_64}; R 4.1-4.5 -> big-sur-{arm64,x86_64}.
_MACOS_BINARY_PROBES: tuple[tuple[str, str], ...] = (
    ("4.6", "sonoma-arm64"),
    ("4.5", "big-sur-arm64"),
    ("4.4", "big-sur-arm64"),
    ("4.3", "big-sur-arm64"),
)
# Linux binary path: bin/linux/{distro}-{arch}/{r_version}/src/contrib/PACKAGES
_LINUX_BINARY_PROBES: tuple[tuple[str, str], ...] = (
    ("4.4", "jammy-x86_64"),
    ("4.4", "noble-x86_64"),
    ("4.3", "jammy-x86_64"),
    ("4.4", "centos7-x86_64"),
)
_WINDOWS_BINARY_R_VERSIONS: tuple[str, ...] = ("4.4", "4.3", "4.5", "4.2")


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

    # -- CRAN binary packages -----------------------------------------------

    def cran_windows_binary_index_reachable(self, repo_name: str) -> tuple[bool, int]:
        """Check if a Windows binary PACKAGES index is served for any recent R version.

        Returns ``(found, status)``. *found* is True only when a probe returns
        HTTP 200 with a real PACKAGES index body. On failure, *status* is the
        most severe status seen across probes (a 5xx outranks a 404) so callers
        can tell a broken server (fail) from an unsynced platform (skip).
        """
        worst = 0
        for r_version in _WINDOWS_BINARY_R_VERSIONS:
            resp = self._client.get(f"/{repo_name}/latest/bin/windows/contrib/{r_version}/PACKAGES")
            if resp.status_code == 200 and "Package:" in resp.text:
                return True, resp.status_code
            worst = max(worst, resp.status_code)
        return False, worst

    def cran_macos_binary_index_reachable(self, repo_name: str) -> tuple[bool, int]:
        """Check if a macOS binary PACKAGES index is served for any recent R version.

        Uses the correct macOS arch per PPM's routing: R 4.6+ -> sonoma-arm64,
        R 4.1-4.5 -> big-sur-arm64. See ``cran_windows_binary_index_reachable``
        for the return-value contract.
        """
        worst = 0
        for r_version, arch in _MACOS_BINARY_PROBES:
            resp = self._client.get(
                f"/{repo_name}/latest/bin/macosx/{arch}/contrib/{r_version}/PACKAGES"
            )
            if resp.status_code == 200 and "Package:" in resp.text:
                return True, resp.status_code
            worst = max(worst, resp.status_code)
        return False, worst

    def cran_linux_binary_index_reachable(self, repo_name: str) -> tuple[bool, int]:
        """Check if a Linux binary PACKAGES index is served for any common distro.

        Uses PPM's binary Linux format:
        ``bin/linux/{distro}-{arch}/{r_version}/src/contrib/PACKAGES``.
        Probes Ubuntu (jammy, noble) and CentOS 7. See
        ``cran_windows_binary_index_reachable`` for the return-value contract.
        """
        worst = 0
        for r_version, distro_arch in _LINUX_BINARY_PROBES:
            resp = self._client.get(
                f"/{repo_name}/latest/bin/linux/{distro_arch}/{r_version}/src/contrib/PACKAGES"
            )
            if resp.status_code == 200 and "Package:" in resp.text:
                return True, resp.status_code
            worst = max(worst, resp.status_code)
        return False, worst

    # -- PyPI binary (wheels) -----------------------------------------------

    def pypi_wheel_available(self, repo_name: str, package: str) -> tuple[bool, int]:
        """Check if any wheel (.whl) file is listed in the PyPI simple index for a package."""
        resp = self._client.get(f"/{repo_name}/latest/simple/{package}/")
        if resp.status_code != 200:
            return False, resp.status_code
        return ".whl" in resp.text, resp.status_code
