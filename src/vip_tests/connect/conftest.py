"""Connect test fixtures and shared step definitions."""

from __future__ import annotations

import io
import tarfile

import pytest
from pytest_bdd import given

pytestmark = [pytest.mark.connect, pytest.mark.xdist_group("connect")]


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None, "Connect client not configured"
    status = connect_client.health()
    assert status < 400, f"Connect returned HTTP {status}"


@given("a valid API key is configured")
def api_key_configured(vip_config):
    assert vip_config.connect.api_key, (
        "VIP_CONNECT_API_KEY is not set. Set it in vip.toml or as an environment variable."
    )


def _make_tar_gz(files: dict[str, str]) -> bytes:
    """Create an in-memory tar.gz archive from a dict of {filename: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Content cleanup (issue #277 pattern): track created content and delete it
# regardless of test outcome, with a session-scoped end-of-run sweep.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _connect_created_guids():
    """Append-only record of content GUIDs created this run (tag-independent)."""
    return []


@pytest.fixture(autouse=True)
def _connect_content_cleanup(connect_client, _connect_created_guids):
    """Delete content created during this test, on pass or fail."""
    start = len(_connect_created_guids)
    yield
    if connect_client is None:
        return
    created = _connect_created_guids[start:]
    if created:
        connect_client.cleanup_content(created)


@pytest.fixture(scope="session", autouse=True)
def _connect_end_of_run_sweep(connect_client, _connect_created_guids):
    """End-of-run safety net: delete tracked GUIDs, then tag-based cross-run sweep."""
    yield
    if connect_client is None:
        return
    if _connect_created_guids:
        connect_client.cleanup_content(_connect_created_guids)
    connect_client.cleanup_vip_content()
