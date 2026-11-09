"""Selftests for the token-authenticated Workbench API methods on WorkbenchClient.

Every payload below is the shape documented at
docs.posit.co/ide/server-pro/admin/workbench_api (``{"result": ...}`` success,
``{"error": {...}}`` inside an HTTP 200 for processing errors, ``get_session``
returning ``{"result": {"sessions": [...], "timestamp": ...}}``). No network:
the client's httpx client is backed by ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from vip.clients.workbench import (
    WorkbenchApiError,
    WorkbenchClient,
    WorkbenchSessionError,
    default_launch_parameters,
    is_ide_offered,
)

URL = "https://wb.example.com"

COMPUTE_ENVS = {
    "clusters": [
        {
            "name": "Local",
            "type": "Local",
            "resourceProfiles": [
                {"name": "small", "displayName": "Small"},
                {"name": "default", "displayName": "Default"},
            ],
            "workbenches": {
                "RStudio": {"supports_interactive_sessions": True, "supports_adhoc_jobs": True},
                "VS Code": {"supports_interactive_sessions": True, "supports_adhoc_jobs": True},
            },
        }
    ],
    "workbenches": {
        "RStudio": {"default_cluster": "Local", "lang": {"name": "R", "available": True}},
        "VS Code": {
            "default_cluster": "Localhost",
            "lang": {"name": "code-server", "available": True},
        },
        "JupyterLab": {"default_cluster": "Local", "lang": {"name": "Jupyter", "available": False}},
    },
}


def _session(sid: str, state: str, label: str = "VIP x - main-1") -> dict:
    """A WorkbenchSession as documented, trimmed to the fields VIP reads."""
    return {
        "id": sid,
        "url": f"/s/0da29cfc78a3{sid}/",
        "activity_state": state,
        "label": label,
        "running": state == "running",
    }


def _sessions_result(*sessions: dict) -> dict:
    return {"result": {"sessions": list(sessions), "timestamp": 1721695376.5}}


def _client(handler, api_key: str = "tok") -> tuple[WorkbenchClient, list[httpx.Request]]:
    """A WorkbenchClient on a MockTransport that keeps the real default headers."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    wc = WorkbenchClient(URL, api_key=api_key)
    headers = dict(wc._client.headers)
    wc._client.close()
    wc._client = httpx.Client(
        base_url=URL, headers=headers, transport=httpx.MockTransport(recording)
    )
    return wc, seen


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


class TestAuthHeader:
    def test_bearer_not_key(self):
        wc = WorkbenchClient(URL, api_key="abc123")
        assert wc._client.headers["Authorization"] == "Bearer abc123"

    def test_no_header_without_a_key(self):
        assert "Authorization" not in WorkbenchClient(URL)._client.headers

    def test_header_reaches_the_request(self):
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": {}}))
        wc.get_version()
        assert seen[0].headers["Authorization"] == "Bearer tok"


class TestRequestEnvelopes:
    def test_get_version_is_a_get(self):
        result = {"version": {"major": "2026"}, "features": ["api"]}
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": result}))
        assert wc.get_version() == result
        assert (seen[0].method, seen[0].url.path) == ("GET", "/api/version")

    def test_get_version_accepts_a_body_without_the_result_wrapper(self):
        body = {"version": {"major": "2026"}, "features": ["api"]}
        wc, _ = _client(lambda r: httpx.Response(200, json=body))
        assert wc.get_version() == body

    def test_get_version_still_raises_on_an_error_envelope(self):
        wc, _ = _client(lambda r: httpx.Response(200, json={"error": {"code": 5, "message": "x"}}))
        with pytest.raises(WorkbenchApiError, match="code 5"):
            wc.get_version()

    def test_launch_session_sends_workbench_username_name_and_launch_parameters(self):
        result = {"url": "/s/0da29cfc78a31acdd5861/", "id": "acdd5861", "project_id": "cfc78a31"}
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": result}))
        params = {"name": "VIP a", "cluster": "Local"}
        out = wc.launch_session("VS Code", username="alice", name="VIP a", launch_parameters=params)
        assert out == result
        assert seen[0].url.path == "/api/launch_session"
        assert _body(seen[0]) == {
            "method": "launch_session",
            "kwparams": {
                "workbench": "VS Code",
                "username": "alice",
                "name": "VIP a",
                "launch_parameters": params,
            },
        }

    def test_launch_session_omits_unset_kwparams(self):
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": {"id": "a"}}))
        wc.launch_session("RStudio")
        assert _body(seen[0])["kwparams"] == {"workbench": "RStudio"}

    def test_get_session_uses_singular_session_id_and_user(self):
        wc, seen = _client(lambda r: httpx.Response(200, json=_sessions_result()))
        wc.get_session("6124d41f", user="alice", fields=["id", "activity_state"])
        assert _body(seen[0]) == {
            "method": "get_session",
            "kwparams": {
                "session_id": "6124d41f",
                "user": "alice",
                "fields": ["id", "activity_state"],
            },
        }

    def test_get_session_returns_the_result_dict(self):
        payload = _sessions_result(_session("6124d41f", "running"))
        wc, _ = _client(lambda r: httpx.Response(200, json=payload))
        assert wc.get_session() == payload["result"]

    def test_stop_session_uses_plural_session_ids_comma_joined(self):
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": {}}))
        assert wc.stop_session(["a1", "b2"], force_quit=True) is True
        assert _body(seen[0]) == {
            "method": "stop_session",
            "kwparams": {"session_ids": "a1,b2", "force_quit": True},
        }

    @pytest.mark.parametrize("body", [{}, {"result": None}, {"result": {}}])
    def test_stop_session_accepts_every_empty_success_body(self, body):
        wc, _ = _client(lambda r: httpx.Response(200, json=body))
        assert wc.stop_session("a1") is True

    def test_stop_session_single_id_and_suspend(self):
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": {}}))
        wc.stop_session("93022e28", suspend=True)
        assert _body(seen[0])["kwparams"] == {"session_ids": "93022e28", "suspend": True}

    def test_get_compute_envs_sends_user_only_when_given(self):
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": COMPUTE_ENVS}))
        assert wc.get_compute_envs() == COMPUTE_ENVS
        wc.get_compute_envs(user="alice")
        assert "kwparams" not in _body(seen[0])
        assert _body(seen[1])["kwparams"] == {"user": "alice"}


class TestErrors:
    def test_http_200_error_envelope_raises_with_code_and_message(self):
        envelope = {"error": {"code": 123, "message": "no capacity to launch"}}
        wc, _ = _client(lambda r: httpx.Response(200, json=envelope))
        with pytest.raises(WorkbenchApiError) as exc_info:
            wc.launch_session("RStudio")
        assert exc_info.value.code == 123
        assert "no capacity to launch" in str(exc_info.value)
        assert "123" in str(exc_info.value)

    def test_401_raises_with_status_code(self):
        wc, _ = _client(lambda r: httpx.Response(401))
        with pytest.raises(WorkbenchApiError) as exc_info:
            wc.get_version()
        assert exc_info.value.status_code == 401

    def test_missing_result_raises(self):
        wc, _ = _client(lambda r: httpx.Response(200, json={}))
        with pytest.raises(WorkbenchApiError, match="no result"):
            wc.get_session()

    def test_non_json_body_raises(self):
        wc, _ = _client(lambda r: httpx.Response(200, text="<html>login</html>"))
        with pytest.raises(WorkbenchApiError, match="non-JSON"):
            wc.get_session()

    def test_transport_error_raises(self):
        def boom(request):
            raise httpx.ConnectError("refused")

        wc, _ = _client(boom)
        with pytest.raises(WorkbenchApiError, match="could not be reached"):
            wc.launch_session("RStudio")

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(401),
            httpx.Response(200, json={"error": {"code": 1, "message": "nope"}}),
            httpx.Response(200, text="not json"),
        ],
    )
    def test_stop_session_never_raises(self, response):
        wc, _ = _client(lambda r: response)
        assert wc.stop_session("a1") is False

    def test_stop_session_swallows_transport_errors(self):
        def boom(request):
            raise httpx.ConnectError("refused")

        wc, _ = _client(boom)
        assert wc.stop_session("a1") is False


class TestWaitForSessionRunning:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr("vip.clients.workbench.time.sleep", lambda s: None)

    def test_returns_once_the_matching_session_is_running(self):
        states = iter(["pending", "starting", "running"])

        def handler(request):
            return httpx.Response(200, json=_sessions_result(_session("6124d41f", next(states))))

        wc, seen = _client(handler)
        wc.wait_for_session_running("6124d41f", user="alice", timeout=60)
        assert len(seen) == 3
        assert _body(seen[0])["kwparams"]["session_id"] == "6124d41f"
        assert _body(seen[0])["kwparams"]["user"] == "alice"

    def test_matches_by_id_among_other_sessions(self):
        payload = _sessions_result(_session("other111", "running"), _session("mine2222", "pending"))
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] > 1:
                return httpx.Response(
                    200,
                    json=_sessions_result(
                        _session("other111", "failed"), _session("mine2222", "running")
                    ),
                )
            return httpx.Response(200, json=payload)

        wc, _ = _client(handler)
        # The sibling's "running"/"failed" states must not decide this session's outcome.
        wc.wait_for_session_running("mine2222", timeout=60)
        assert calls["n"] == 2

    @pytest.mark.parametrize("state", ["failed", "killed"])
    def test_fails_fast_on_a_terminal_failure_state(self, state):
        wc, seen = _client(
            lambda r: httpx.Response(200, json=_sessions_result(_session("6124d41f", state)))
        )
        with pytest.raises(WorkbenchSessionError, match=state):
            wc.wait_for_session_running("6124d41f", timeout=600)
        assert len(seen) == 1

    def test_timeout_names_the_last_state(self, monkeypatch):
        clock = iter([0.0, 1.0, 2.0, 100.0])
        monkeypatch.setattr("vip.clients.workbench.time.monotonic", lambda: next(clock))
        wc, _ = _client(
            lambda r: httpx.Response(200, json=_sessions_result(_session("6124d41f", "starting")))
        )
        with pytest.raises(WorkbenchSessionError) as exc_info:
            wc.wait_for_session_running("6124d41f", timeout=10)
        assert "'starting'" in str(exc_info.value)

    def test_timeout_when_the_session_is_never_listed(self, monkeypatch):
        clock = iter([0.0, 100.0])
        monkeypatch.setattr("vip.clients.workbench.time.monotonic", lambda: next(clock))
        wc, _ = _client(lambda r: httpx.Response(200, json=_sessions_result()))
        with pytest.raises(WorkbenchSessionError, match="not listed"):
            wc.wait_for_session_running("6124d41f", timeout=10)

    def test_error_envelope_while_waiting_surfaces(self):
        wc, _ = _client(
            lambda r: httpx.Response(200, json={"error": {"code": 7, "message": "boom"}})
        )
        with pytest.raises(WorkbenchApiError, match="boom"):
            wc.wait_for_session_running("6124d41f", timeout=10)

    def test_result_without_a_sessions_list_raises(self):
        wc, _ = _client(lambda r: httpx.Response(200, json={"result": {"timestamp": 1}}))
        with pytest.raises(WorkbenchApiError, match="sessions"):
            wc.wait_for_session_running("6124d41f", timeout=10)


class TestComputeEnvHelpers:
    def test_ide_offered_requires_a_workbenches_entry(self):
        assert is_ide_offered(COMPUTE_ENVS, "RStudio") is True
        assert is_ide_offered(COMPUTE_ENVS, "Positron") is False

    def test_ide_with_an_unavailable_runtime_is_not_offered(self):
        assert is_ide_offered(COMPUTE_ENVS, "JupyterLab") is False

    def test_default_cluster_is_used_when_it_names_a_cluster(self):
        assert default_launch_parameters(COMPUTE_ENVS, "RStudio", "VIP a") == {
            "name": "VIP a",
            "cluster": "Local",
            "resource_profile": "default",
        }

    def test_first_resource_profile_is_used_when_none_is_called_default(self):
        envs = {
            "clusters": [
                {"name": "Local", "resourceProfiles": [{"name": "small"}, {"name": "large"}]}
            ],
            "workbenches": {"RStudio": {"default_cluster": "Local"}},
        }
        assert default_launch_parameters(envs, "RStudio", "n")["resource_profile"] == "small"

    def test_no_resource_profile_is_sent_when_the_cluster_defines_none(self):
        envs = {
            "clusters": [{"name": "Local", "resourceProfiles": []}],
            "workbenches": {"RStudio": {"default_cluster": "Local"}},
        }
        assert default_launch_parameters(envs, "RStudio", "n") == {
            "name": "n",
            "cluster": "Local",
        }

    def test_unknown_default_cluster_falls_back_to_an_interactive_cluster(self):
        # The docs' own example lists default_cluster "Localhost" for a cluster named "Local".
        assert default_launch_parameters(COMPUTE_ENVS, "VS Code", "VIP a")["cluster"] == "Local"

    def test_empty_compute_envs_fall_back_to_local(self):
        assert default_launch_parameters({}, "RStudio", "VIP a") == {
            "name": "VIP a",
            "cluster": "Local",
        }


class TestGetLaunchComputeEnvs:
    def test_asks_for_the_users_environments(self):
        wc, seen = _client(lambda r: httpx.Response(200, json={"result": COMPUTE_ENVS}))
        assert wc.get_launch_compute_envs("alice") == COMPUTE_ENVS
        assert _body(seen[0])["kwparams"] == {"user": "alice"}

    def test_falls_back_to_the_token_owners_environments_on_a_processing_error(self):
        def handler(request):
            if "kwparams" in _body(request):
                return httpx.Response(200, json={"error": {"code": 9, "message": "not allowed"}})
            return httpx.Response(200, json={"result": COMPUTE_ENVS})

        wc, seen = _client(handler)
        assert wc.get_launch_compute_envs("alice") == COMPUTE_ENVS
        assert len(seen) == 2

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_a_refused_token_is_not_retried(self, status):
        wc, seen = _client(lambda r: httpx.Response(status))
        with pytest.raises(WorkbenchApiError) as exc_info:
            wc.get_launch_compute_envs("alice")
        assert exc_info.value.status_code == status
        assert len(seen) == 1


class TestQuitVipSessionsViaApi:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr("vip.clients.workbench.time.sleep", lambda s: None)

    def test_stops_only_vip_sessions_of_the_owner_and_skips_exited_ones(self):
        listing = _sessions_result(
            _session("aaaa1111", "running", "VIP t.py - gw1-100"),
            _session("bbbb2222", "running", "VIP t.py - gw2-100"),
            _session("cccc3333", "running", "My analysis"),
            _session("dddd4444", "finished", "VIP t.py - gw1-101"),
        )
        stopped: list[str] = []
        live = {"on": True}

        def handler(request):
            body = _body(request)
            if body["method"] == "stop_session":
                stopped.extend(body["kwparams"]["session_ids"].split(","))
                live["on"] = False
                return httpx.Response(200, json={"result": {}})
            assert body["kwparams"]["user"] == "alice"
            return httpx.Response(200, json=listing if live["on"] else _sessions_result())

        wc, _ = _client(handler)
        assert wc.quit_vip_sessions_via_api("alice", owner="gw1") == 1
        assert stopped == ["aaaa1111"]

    def test_owner_none_stops_every_vip_session(self):
        listing = _sessions_result(
            _session("aaaa1111", "running", "VIP t.py - gw1-100"),
            _session("bbbb2222", "running", "_vip_cap_gw2_1_Small_0"),
        )
        live = {"on": True}
        stopped: list[str] = []

        def handler(request):
            body = _body(request)
            if body["method"] == "stop_session":
                stopped.extend(body["kwparams"]["session_ids"].split(","))
                live["on"] = False
                return httpx.Response(200, json={"result": {}})
            return httpx.Response(200, json=listing if live["on"] else _sessions_result())

        wc, _ = _client(handler)
        assert wc.quit_vip_sessions_via_api("alice") == 2
        assert sorted(stopped) == ["aaaa1111", "bbbb2222"]

    def test_warns_when_a_session_survives_every_retry(self, caplog):
        listing = _sessions_result(_session("aaaa1111", "running", "VIP t.py - main-1"))

        def handler(request):
            if _body(request)["method"] == "stop_session":
                return httpx.Response(200, json={"result": {}})
            return httpx.Response(200, json=listing)

        wc, _ = _client(handler)
        with caplog.at_level(logging.WARNING, logger="vip.clients.workbench"):
            wc.quit_vip_sessions_via_api("alice", owner="main")
        assert "aaaa1111" in caplog.text

    def test_raises_when_the_listing_fails(self):
        wc, _ = _client(lambda r: httpx.Response(401))
        with pytest.raises(WorkbenchApiError):
            wc.quit_vip_sessions_via_api("alice")
