"""Selftests for the pluggable load engine."""

from __future__ import annotations

import http.server
import queue
import sys
import threading

import httpx
import pytest

from vip.config import PerformanceConfig
from vip.load_engine import (
    LoadTestResult,
    _build_result,
    _log_request,
    _run_locust,
    _stop_plugin_heartbeat_before_gevent,
    classify_repos,
    run_load_test,
    run_user_simulation,
)

# macOS GitHub runners can't sustain hundreds of concurrent localhost
# connections (tighter ephemeral port range and listen backlog than Linux),
# so the async load tests at 100+ requests see real failures unrelated to
# the load engine. Skip those there; the same code paths run on Linux.
_skip_high_concurrency_on_macos = pytest.mark.skipif(
    sys.platform == "darwin",
    reason="high-concurrency localhost loads are flaky on macOS CI runners",
)

# ---------------------------------------------------------------------------
# Mock HTTP server
# ---------------------------------------------------------------------------


class _OKHandler(http.server.BaseHTTPRequestHandler):
    """Return 200 OK for every GET request."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_args):
        pass  # suppress noisy request logging


class _ThreadedHTTPServer(http.server.HTTPServer):
    """HTTPServer that serves requests from a pool of pre-started threads.

    Deliberately *not* ``ThreadingHTTPServer``.  That class starts a fresh
    thread per request, and a thread started while coverage's
    ``threading.settrace`` hook is installed can die in
    ``Thread._bootstrap_inner`` before ``run()`` -- see
    ``TestMockServerThreads`` for the full mechanism.  With a thread per
    request, one such death silently swallows a request: the connection is
    accepted and never answered, the client waits out the whole 30s load-test
    timeout, and the run reports a failure rate the load engine did not
    produce.  These tests fire up to 1000 requests apiece, so the rare
    per-thread race turns into a recurring CI flake.

    The pool moves every thread start to fixture setup, where a death costs a
    redundant worker rather than a request.  64 workers absorb the 200
    concurrent connections the async tests open: each request is answered
    immediately, so workers are never held.
    """

    allow_reuse_address = True
    pool_size = 64

    # ``socketserver.TCPServer`` defaults this to 5, which is the ``listen()``
    # backlog -- not a limit on concurrent work.  The load tests open 50-1000
    # connections near-simultaneously, faster than ``serve_forever`` can accept
    # them, so with the default anything past the fifth queued connection is
    # reset by the kernel before it is ever accepted.  Those resets are counted
    # as request failures, so the assertions read a load-engine failure rate
    # that the fixture caused.  macOS is stricter about the ceiling than Linux,
    # which is why this surfaced there first.
    request_queue_size = 128

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._requests: queue.Queue = queue.Queue()
        self._workers = [
            threading.Thread(target=self._serve_requests, daemon=True)
            for _ in range(self.pool_size)
        ]
        for worker in self._workers:
            worker.start()

    def process_request(self, request, client_address):
        """Hand the accepted socket to the pool instead of a new thread."""
        self._requests.put((request, client_address))

    def _serve_requests(self):
        while True:
            item = self._requests.get()
            if item is None:  # shutdown sentinel
                return
            request, client_address = item
            try:
                self.finish_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)

    def server_close(self):
        for _ in self._workers:
            self._requests.put(None)
        for worker in self._workers:
            worker.join(timeout=2)
        super().server_close()


@pytest.fixture(scope="module")
def mock_server():
    server = _ThreadedHTTPServer(("127.0.0.1", 0), _OKHandler)
    url = f"http://127.0.0.1:{server.server_address[1]}/ping"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield url
    server.shutdown()
    server.server_close()


class TestMockServerThreads:
    def test_no_thread_starts_while_requests_are_in_flight(self, mock_server, monkeypatch):
        """Handler threads must be pre-started, never spawned per request.

        A thread that starts while coverage's ``threading.settrace`` hook is
        installed can die inside ``Thread._bootstrap_inner`` -- at
        ``_sys.settrace(_trace_hook)``, before ``run()`` ever executes -- with
        "Cannot install a trace function while another trace function is being
        installed".  A thread-per-request server loses the whole request when
        that happens: the socket is already accepted, nothing answers it, and
        the client burns its full 30s timeout before recording a failure the
        load engine never caused.  Served from a pre-started pool, the same
        thread death costs one redundant worker and no request.
        """
        # Warm up outside the spy so the fixture's own thread creation is never
        # counted, whichever test in this module reaches the fixture first.
        assert httpx.get(mock_server, timeout=10).status_code == 200

        started: list[str] = []
        real_start = threading.Thread.start

        def _spy_start(thread):
            started.append(thread.name)
            return real_start(thread)

        monkeypatch.setattr(threading.Thread, "start", _spy_start)

        for _ in range(20):
            assert httpx.get(mock_server, timeout=10).status_code == 200

        assert started == [], f"threads started while serving requests: {started}"


# ---------------------------------------------------------------------------
# LoadTestResult
# ---------------------------------------------------------------------------


class TestLoadTestResult:
    def test_fields(self):
        r = LoadTestResult(
            total=10, successes=9, failure_rate=0.1, p95_response_time=0.5, results=[]
        )
        assert r.total == 10
        assert r.successes == 9
        assert r.failure_rate == pytest.approx(0.1)
        assert r.p95_response_time == 0.5

    def test_build_result_all_success(self):
        raw = [
            {"elapsed": 0.1, "status": 200, "error": None},
            {"elapsed": 0.2, "status": 200, "error": None},
        ]
        result = _build_result(raw)
        assert result.total == 2
        assert result.successes == 2
        assert result.failure_rate == 0.0

    def test_build_result_with_errors(self):
        raw = [
            {"elapsed": 0.1, "status": 200, "error": None},
            {"elapsed": 0.2, "status": None, "error": "timeout"},
        ]
        result = _build_result(raw)
        assert result.total == 2
        assert result.successes == 1
        assert result.failure_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Threadpool backend
# ---------------------------------------------------------------------------


class TestThreadpool:
    def test_returns_correct_count(self, mock_server):
        config = PerformanceConfig(load_test_tool="threadpool")
        result = run_load_test(mock_server, {}, 10, config)
        assert result.total == 10

    def test_all_succeed(self, mock_server):
        config = PerformanceConfig(load_test_tool="threadpool")
        result = run_load_test(mock_server, {}, 20, config)
        assert result.failure_rate == 0.0
        assert result.successes == 20


# ---------------------------------------------------------------------------
# Async backend
# ---------------------------------------------------------------------------


class TestAsync:
    def test_returns_correct_count(self, mock_server):
        config = PerformanceConfig(load_test_tool="async")
        result = run_load_test(mock_server, {}, 10, config)
        assert result.total == 10

    @_skip_high_concurrency_on_macos
    def test_all_succeed(self, mock_server):
        config = PerformanceConfig(load_test_tool="async")
        result = run_load_test(mock_server, {}, 100, config)
        assert result.failure_rate == 0.0

    @_skip_high_concurrency_on_macos
    def test_1k_users(self, mock_server):
        config = PerformanceConfig(load_test_tool="async", load_max_connections=200)
        result = run_load_test(mock_server, {}, 1_000, config)
        assert result.total == 1_000
        assert result.failure_rate < 0.05


# ---------------------------------------------------------------------------
# Auto routing
# ---------------------------------------------------------------------------


class TestAutoRouting:
    def test_small_uses_threadpool(self, mock_server):
        config = PerformanceConfig(load_test_tool="auto")
        result = run_load_test(mock_server, {}, 50, config)
        assert result.total == 50
        assert result.failure_rate == 0.0

    @_skip_high_concurrency_on_macos
    def test_large_uses_async(self, mock_server):
        config = PerformanceConfig(load_test_tool="auto")
        result = run_load_test(mock_server, {}, 200, config)
        assert result.total == 200
        assert result.failure_rate == 0.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_bad_url(self):
        config = PerformanceConfig(load_test_tool="threadpool")
        result = run_load_test("http://127.0.0.1:1/nope", {}, 3, config)
        assert result.total == 3
        assert result.failure_rate == 1.0
        assert all(r["error"] is not None for r in result.results)

    def test_invalid_tool(self, mock_server):
        config = PerformanceConfig(load_test_tool="bogus")
        with pytest.raises(ValueError, match="Unknown load_test_tool"):
            run_load_test(mock_server, {}, 10, config)

    def test_locust_not_installed_raises(self, mock_server, monkeypatch):
        monkeypatch.setattr("vip.load_engine._locust_available", lambda: False)
        config = PerformanceConfig(load_test_tool="locust")
        with pytest.raises(RuntimeError, match="locust not installed"):
            run_load_test(mock_server, {}, 10, config)


# ---------------------------------------------------------------------------
# Repo classification
# ---------------------------------------------------------------------------


class TestClassifyRepos:
    """classify_repos should route repos to CRAN/PyPI lists by type."""

    def test_mixed_repo_list(self):
        repos = [
            {"name": "cran", "type": "R"},
            {"name": "pypi", "type": "Python"},
            {"name": "bio", "type": "Bioconductor"},
        ]
        cran, pypi = classify_repos(repos)
        assert cran == ["cran"]
        assert pypi == ["pypi"]

    def test_case_insensitive(self):
        repos = [
            {"name": "a", "type": "r"},
            {"name": "b", "type": "PYTHON"},
            {"name": "c", "type": " R "},
        ]
        cran, pypi = classify_repos(repos)
        assert cran == ["a", "c"]
        assert pypi == ["b"]

    def test_aliases(self):
        repos = [
            {"name": "x", "type": "cran"},
            {"name": "y", "type": "pypi"},
        ]
        cran, pypi = classify_repos(repos)
        assert cran == ["x"]
        assert pypi == ["y"]

    def test_unknown_type_ignored(self):
        repos = [{"name": "vsx", "type": "VSX"}, {"name": "snap", "type": "Snapshot"}]
        cran, pypi = classify_repos(repos)
        assert cran == []
        assert pypi == []

    def test_missing_type_ignored(self):
        repos = [{"name": "mystery"}]
        cran, pypi = classify_repos(repos)
        assert cran == []
        assert pypi == []

    def test_empty_name_skipped(self):
        repos = [{"name": "", "type": "R"}, {"name": "good", "type": "R"}]
        cran, pypi = classify_repos(repos)
        assert cran == ["good"]

    def test_empty_list(self):
        cran, pypi = classify_repos([])
        assert cran == []
        assert pypi == []

    def test_non_dict_items_skipped(self):
        repos = [None, "bad", 42, {"name": "cran", "type": "R"}]
        cran, pypi = classify_repos(repos)
        assert cran == ["cran"]
        assert pypi == []


# ---------------------------------------------------------------------------
# User simulation verbose output
# ---------------------------------------------------------------------------


class TestLogRequest:
    """The _log_request callback writes to fd 2 (bypasses gevent buffering)."""

    def test_success_line(self, capfd):
        _log_request(
            request_type="GET",
            name="/__api__/repos",
            response_time=342.5,
            response_length=1024,
            exception=None,
        )
        line = capfd.readouterr().err.strip()
        assert "[locust] GET /__api__/repos" in line
        assert "0.34s" in line
        assert "200" not in line  # no status code in success line

    def test_failure_line(self, capfd):
        _log_request(
            request_type="GET",
            name="/timeout",
            response_time=30000.0,
            response_length=0,
            exception=ConnectionError("timed out"),
        )
        line = capfd.readouterr().err.strip()
        assert "[locust] GET /timeout" in line
        assert "FAIL" in line
        assert "timed out" in line

    def test_zero_response_time(self, capfd):
        _log_request(
            request_type="GET",
            name="/fast",
            response_time=0,
            response_length=0,
            exception=None,
        )
        line = capfd.readouterr().err.strip()
        assert "0.00s" in line


# ---------------------------------------------------------------------------
# Heartbeat stop before gevent import
# ---------------------------------------------------------------------------


class _RecordingHeartbeat:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class TestStopPluginHeartbeatBeforeGevent:
    """``_stop_plugin_heartbeat_before_gevent`` must shut down the plugin
    heartbeat thread before any caller triggers ``gevent.monkey.patch_all``.
    The locust/gevent import path deadlocks if a live ``threading.Thread``
    is running, so both ``_run_locust`` and ``run_user_simulation`` must
    invoke this helper first.
    """

    def test_stops_active_heartbeat(self, monkeypatch):
        import vip.plugin as plugin

        hb = _RecordingHeartbeat()
        monkeypatch.setattr(plugin, "_current_heartbeat", hb)
        _stop_plugin_heartbeat_before_gevent()
        assert hb.stopped is True

    def test_noop_when_no_heartbeat(self, monkeypatch):
        import vip.plugin as plugin

        monkeypatch.setattr(plugin, "_current_heartbeat", None)
        # Must not raise even though no heartbeat is registered.
        _stop_plugin_heartbeat_before_gevent()

    def test_run_locust_calls_helper_before_gevent_import(self):
        """_run_locust must call the helper before any locust/gevent import."""
        self._assert_helper_precedes_gevent_import(_run_locust)

    def test_run_user_simulation_calls_helper_before_gevent_import(self):
        """run_user_simulation must call the helper before any locust/gevent import."""
        self._assert_helper_precedes_gevent_import(run_user_simulation)

    @staticmethod
    def _assert_helper_precedes_gevent_import(func):
        """Inspect the function AST: helper call must precede any locust/gevent
        import statement. Running the function would deadlock on real gevent
        coroutines when the ordering is wrong, so verify statically instead.
        """
        import ast
        import inspect
        import textwrap

        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)

        helper_line = None
        gevent_line = None
        locust_line = None
        for node in ast.walk(func_def):
            if (
                helper_line is None
                and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_stop_plugin_heartbeat_before_gevent"
            ):
                helper_line = node.lineno
            elif gevent_line is None and isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "gevent":
                        gevent_line = node.lineno
            elif locust_line is None and isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("locust"):
                    locust_line = node.lineno

        name = func.__name__
        assert helper_line is not None, f"{name} does not call the heartbeat helper"
        assert gevent_line is not None, f"{name} does not import gevent"
        assert locust_line is not None, f"{name} does not import from locust"
        assert helper_line < gevent_line, (
            f"{name} imports gevent before calling the heartbeat helper"
        )
        assert helper_line < locust_line, (
            f"{name} imports locust before calling the heartbeat helper"
        )
