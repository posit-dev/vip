"""Workbench test fixtures."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.workbench


@pytest.fixture(autouse=True)
def _cleanup_sessions(page, workbench_client):
    """Quit any Workbench sessions created during the test."""
    yield
    if workbench_client is None:
        return
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
        sessions = workbench_client.list_sessions(cookies)
        for session in sessions:
            sid = session.get("id") or session.get("session_id", "")
            if sid:
                workbench_client.quit_session(sid, cookies)
    except Exception:
        # Best-effort cleanup; don't mask test failures.
        pass
