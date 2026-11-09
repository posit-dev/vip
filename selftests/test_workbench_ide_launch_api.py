"""Selftests for the ``--api-auth`` Workbench IDE-launch scenarios (#504).

Two things are pinned here without importing the pytest-bdd step module (see
CLAUDE.md): which items ``--api-auth`` keeps, and how the scenarios behave end to
end. The end-to-end half runs ``test_ide_launch_api.py`` in a subprocess against
a throwaway local HTTP server that answers with the documented Workbench API
shapes, so no real Workbench or browser is involved.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKBENCH_DIR = _REPO_ROOT / "src" / "vip_tests" / "workbench"
_API_TEST = _WORKBENCH_DIR / "test_ide_launch_api.py"
_TOKEN = "selftest-token"
_NODEID_RE = re.compile(r"^\S+::\S+$")

_COMPUTE_ENVS = {
    "clusters": [
        {
            "name": "Local",
            "type": "Local",
            "resourceProfiles": [{"name": "default"}],
            "workbenches": {"RStudio": {"supports_interactive_sessions": True}},
        }
    ],
    "workbenches": {"RStudio": {"default_cluster": "Local", "lang": {"available": True}}},
}


class _FakeWorkbench(ThreadingHTTPServer):
    """A Workbench API that launches sessions which become running on the second poll."""

    def __init__(self, token: str):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.token = token
        self.sessions: dict[str, dict] = {}
        self.polls: dict[str, int] = {}
        self.calls: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    server: _FakeWorkbench

    def log_message(self, *args) -> None:
        pass

    def _reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.token}"

    def do_GET(self) -> None:
        if not self._authorized():
            self._reply(401, {})
        elif self.path == "/api/version":
            self._reply(200, {"version": {"major": "2026"}, "features": []})
        else:
            self._reply(404, {})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not self._authorized():
            self._reply(401, {})
            return
        method, kwparams = body["method"], body.get("kwparams", {})
        self.server.calls.append(body)
        sessions = self.server.sessions
        if method == "get_compute_envs":
            self._reply(200, {"result": _COMPUTE_ENVS})
        elif method == "launch_session":
            sid = f"sess{len(sessions) + 1:04d}"
            sessions[sid] = {"id": sid, "label": kwparams["name"], "activity_state": "starting"}
            self._reply(200, {"result": {"id": sid, "url": f"/s/{sid}/", "project_id": "p1"}})
        elif method == "get_session":
            listed = []
            for sid, session in sessions.items():
                self.server.polls[sid] = self.server.polls.get(sid, 0) + 1
                if self.server.polls[sid] >= 2:
                    session["activity_state"] = "running"
                if kwparams.get("session_id") in (None, sid):
                    listed.append(dict(session))
            self._reply(200, {"result": {"sessions": listed, "timestamp": 1721695376.5}})
        elif method == "stop_session":
            for sid in kwparams["session_ids"].split(","):
                sessions.pop(sid, None)
            self._reply(200, {"result": {}})
        else:
            self._reply(200, {"error": {"code": 1, "message": f"unknown method {method}"}})


@pytest.fixture
def fake_workbench():
    server = _FakeWorkbench(_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _write_config(tmp_path: Path, url: str, *, username: bool = True) -> Path:
    config = tmp_path / "vip.toml"
    auth = '[auth]\nprovider = "password"\nusername = "alice"\n' if username else ""
    config.write_text(
        f'[general]\ndeployment_name = "Selftest"\n[connect]\nenabled = false\n'
        f'[workbench]\nenabled = true\nurl = "{url}"\n{auth}',
        encoding="utf-8",
    )
    return config


def _env(token: str | None) -> dict[str, str]:
    # The parent may itself be an xdist worker; the child must name sessions as "main".
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("VIP_", "PYTEST_XDIST", "PYTEST_CURRENT"))
    }
    if token is not None:
        env["VIP_WORKBENCH_API_KEY"] = token
    return env


def _collect_api_auth_files(tmp_path: Path) -> set[str]:
    config = _write_config(tmp_path, "https://wb.example.com")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_WORKBENCH_DIR),
            "--collect-only",
            "-q",
            "--api-auth",
            f"--vip-config={config}",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=_env(None),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nodeids = [
        line.strip() for line in result.stdout.splitlines() if _NODEID_RE.match(line.strip())
    ]
    return {Path(n.split("::", 1)[0]).stem for n in nodeids}


def _run_scenarios(
    tmp_path: Path, config: Path, token: str | None, *extra: str
) -> list[ET.Element]:
    junit = tmp_path / "junit.xml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_API_TEST),
            "--api-auth",
            "-n",
            "0",
            "-p",
            "no:randomly",
            f"--vip-config={config}",
            f"--junitxml={junit}",
            *extra,
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=_env(token),
        timeout=120,
    )
    assert junit.exists(), result.stdout + result.stderr
    return list(ET.parse(junit).getroot().iter("testcase"))


class TestApiAuthSelection:
    def test_api_launch_tests_are_kept_and_browser_tests_dropped(self, tmp_path):
        files = _collect_api_auth_files(tmp_path)
        assert "test_ide_launch_api" in files
        # Plain @workbench scenarios drive a browser, so --api-auth must still drop them.
        assert "test_ide_launch" not in files
        assert "test_auth" not in files


class TestApiLaunchScenarios:
    def test_rstudio_launches_runs_and_is_stopped(self, tmp_path, fake_workbench):
        config = _write_config(tmp_path, f"http://127.0.0.1:{fake_workbench.server_port}")
        cases = _run_scenarios(tmp_path, config, _TOKEN, "-k", "rstudio")
        assert [c.get("name") for c in cases] == ["test_launch_rstudio_api[chromium]"]
        assert not list(cases[0]), ET.tostring(cases[0], encoding="unicode")
        launch = next(c for c in fake_workbench.calls if c["method"] == "launch_session")
        assert launch["kwparams"]["workbench"] == "RStudio"
        assert launch["kwparams"]["username"] == "alice"
        assert re.fullmatch(r"VIP test_ide_launch_api\.py - main-\d+", launch["kwparams"]["name"])
        assert launch["kwparams"]["launch_parameters"]["cluster"] == "Local"
        assert launch["kwparams"]["launch_parameters"]["resource_profile"] == "default"
        assert fake_workbench.sessions == {}

    def test_ide_not_offered_is_a_not_applicable_skip(self, tmp_path, fake_workbench):
        config = _write_config(tmp_path, f"http://127.0.0.1:{fake_workbench.server_port}")
        (case,) = _run_scenarios(tmp_path, config, _TOKEN, "-k", "positron")
        skipped = case.find("skipped")
        assert skipped is not None
        assert "UNPROVEN" not in skipped.get("message", "")
        assert "not offered" in skipped.get("message", "")
        assert not any(c["method"] == "launch_session" for c in fake_workbench.calls)

    def test_no_token_is_a_not_applicable_skip(self, tmp_path, fake_workbench):
        config = _write_config(tmp_path, f"http://127.0.0.1:{fake_workbench.server_port}")
        (case,) = _run_scenarios(tmp_path, config, None, "-k", "rstudio")
        skipped = case.find("skipped")
        assert skipped is not None
        assert "UNPROVEN" not in skipped.get("message", "")
        assert fake_workbench.calls == []

    def test_rejected_token_is_unproven(self, tmp_path, fake_workbench):
        config = _write_config(tmp_path, f"http://127.0.0.1:{fake_workbench.server_port}")
        (case,) = _run_scenarios(tmp_path, config, "wrong-token", "-k", "rstudio")
        skipped = case.find("skipped")
        assert skipped is not None
        assert skipped.get("message", "").startswith("UNPROVEN")
        assert "HTTP 401" in skipped.get("message", "")
