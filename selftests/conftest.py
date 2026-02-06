"""Selftest fixtures.

These tests verify the VIP framework itself and can run without any Posit
products.  They are separate from the ``tests/`` directory which contains
the actual verification suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Enable the pytester fixture for plugin integration tests.
pytest_plugins = ["pytester"]


@pytest.fixture()
def tmp_toml(tmp_path: Path):
    """Helper that writes a TOML string to a temp file and returns the path."""

    def _write(content: str) -> Path:
        p = tmp_path / "vip.toml"
        p.write_text(content)
        return p

    return _write


@pytest.fixture()
def sample_results_json(tmp_path: Path) -> Path:
    """Write a sample results.json and return its path."""
    import json

    data = {
        "generated_at": "2026-01-15T12:00:00+00:00",
        "deployment_name": "Selftest Deployment",
        "exit_status": 0,
        "results": [
            {
                "nodeid": "tests/connect/test_auth.py::test_connect_login_ui",
                "outcome": "passed",
                "duration": 1.23,
                "longrepr": None,
                "markers": ["connect"],
            },
            {
                "nodeid": "tests/connect/test_auth.py::test_connect_login_api",
                "outcome": "passed",
                "duration": 0.45,
                "longrepr": None,
                "markers": ["connect"],
            },
            {
                "nodeid": "tests/workbench/test_auth.py::test_workbench_login",
                "outcome": "skipped",
                "duration": 0.0,
                "longrepr": "Workbench is not configured",
                "markers": ["workbench"],
            },
            {
                "nodeid": "tests/prerequisites/test_components.py::test_connect_reachable",
                "outcome": "passed",
                "duration": 0.12,
                "longrepr": None,
                "markers": ["prerequisites"],
            },
            {
                "nodeid": "tests/security/test_https.py::test_connect_https",
                "outcome": "failed",
                "duration": 0.8,
                "longrepr": "AssertionError: HTTP not redirected",
                "markers": ["security"],
            },
        ],
    }
    p = tmp_path / "results.json"
    p.write_text(json.dumps(data))
    return p
