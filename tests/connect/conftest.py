"""Connect test fixtures and shared step definitions."""

from __future__ import annotations

import io
import tarfile

import pytest
from pytest_bdd import given

pytestmark = pytest.mark.connect


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None, "Connect client not configured"
    status = connect_client.server_status()
    assert status < 400, f"Connect returned HTTP {status}"


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
