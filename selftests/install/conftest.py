"""Fixtures for install/uninstall selftests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def manifest_dir(tmp_path: Path) -> Path:
    """A temp dir to act as the project root, where .vip-install.json lives."""
    return tmp_path
