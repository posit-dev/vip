"""Selftests for the pluggable load engine."""

from __future__ import annotations

import http.server
import threading

import pytest

from vip.config import PerformanceConfig
from vip.load_engine import LoadTestResult, _build_result, _log_request, run_load_test

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


class _ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    """HTTPServer that handles each request in a new thread."""

    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture(scope="module")
def mock_server():
    server = _ThreadedHTTPServer(("127.0.0.1", 0), _OKHandler)
    url = f"http://127.0.0.1:{server.server_address[1]}/ping"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield url
    server.shutdown()


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

    def test_all_succeed(self, mock_server):
        config = PerformanceConfig(load_test_tool="async")
        result = run_load_test(mock_server, {}, 100, config)
        assert result.failure_rate == 0.0

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
