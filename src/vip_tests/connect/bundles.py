"""Shared content bundles for Connect deployment.

Single source of truth for the content VIP deploys, so the Connect deploy test
(``connect/test_content_deploy.py``) and the Workbench publish test
(``workbench/test_publish_to_connect.py``) use byte-identical bundles.  The
Workbench test writes these files into the session's own filesystem via the IDE
terminal and deploys them with ``rsconnect deploy manifest`` (which, unlike
``deploy shiny``, deploys any content type -- including R -- from a prepared
``manifest.json`` and builds server-side, so no local R is required).
"""

from __future__ import annotations

import json
import pathlib

# The minimal R Shiny app: a page containing only the text "VIP test" and an
# empty server.  Its MD5 is baked into shiny_manifest.json's files block, so
# this string must not change without regenerating that checksum.
_SHINY_APP_R = (
    "library(shiny)\n"
    'ui <- fluidPage("VIP test")\n'
    "server <- function(input, output, session) {}\n"
    "shinyApp(ui, server)\n"
)

# Location of the reference manifest in the public repo.  The Workbench publish
# test cannot read the pytest host's filesystem from inside the session, so it
# downloads this manifest into the session over HTTPS instead of typing its
# ~80 KB through the terminal.  Kept next to the manifest itself so both stay in
# sync.
MANIFEST_REPO = "posit-dev/vip"
MANIFEST_REPO_PATH = "src/vip_tests/connect/shiny_manifest.json"


def manifest_raw_url(ref: str) -> str:
    """Return the raw GitHub URL for ``shiny_manifest.json`` at *ref*.

    *ref* is any git ref the public repo exposes (a release tag like
    ``v0.58.7``, a branch, or a commit SHA).  Pinning to the installed version's
    tag keeps the downloaded manifest in lockstep with the ``_SHINY_APP_R``
    checksum shipped in the same release.
    """
    return f"https://raw.githubusercontent.com/{MANIFEST_REPO}/{ref}/{MANIFEST_REPO_PATH}"


def _latest_version(versions: list[str]) -> str:
    """Return the highest version string by numeric component.

    Connect's server_settings list installations in install order, not by
    version, so picking [0] can return the oldest R/Python.  Choosing the
    newest matches the regenerated manifests, which target current packages.
    """

    def key(v: str) -> tuple:
        parts = []
        for p in v.split("."):
            try:
                parts.append((0, int(p)))
            except ValueError:
                parts.append((1, p))
        return tuple(parts)

    return max(versions, key=key)


def build_shiny_bundle_files(r_versions: list[str]) -> dict[str, str]:
    """Return the R Shiny bundle as ``{filename: content}``.

    Loads the reference ``shiny_manifest.json`` (the full transitive package
    closure) and patches its ``platform`` to the newest R installed on the
    server, exactly as the Connect deploy test does.  Callers must skip when
    *r_versions* is empty (no R on Connect ⇒ nothing to build against).

    Returns ``{"app.R": ..., "manifest.json": ...}`` -- suitable both for an
    API bundle upload and for ``rsconnect deploy manifest``.
    """
    manifest = json.loads((pathlib.Path(__file__).parent / "shiny_manifest.json").read_text())
    manifest["platform"] = _latest_version(r_versions)
    return {"app.R": _SHINY_APP_R, "manifest.json": json.dumps(manifest)}
