"""Product cleanup must not make unauthenticated checks require API credentials."""

from __future__ import annotations

from pathlib import Path

import pytest

_PRODUCT_TESTS = Path(__file__).resolve().parents[1] / "src" / "vip_tests"


@pytest.fixture
def cleanup_suite(pytester, monkeypatch):
    monkeypatch.delenv("VIP_CONNECT_API_KEY", raising=False)
    pytester.makeconftest((_PRODUCT_TESTS / "conftest.py").read_text(encoding="utf-8"))
    pytester.makefile(
        ".toml",
        vip='[connect]\nenabled = true\nurl = "http://connect.example.test"\n',
    )
    return pytester


@pytest.mark.parametrize("status", [200, 503])
def test_unauthenticated_connect_health_check(cleanup_suite, status):
    suite = cleanup_suite
    for name in ("test_components.py", "test_components.feature"):
        (suite.path / name).write_text(
            (_PRODUCT_TESTS / "prerequisites" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    with (suite.path / "conftest.py").open("a", encoding="utf-8") as conftest:
        conftest.write(f"""
import httpx

@pytest.fixture(autouse=True)
def mock_health_request(monkeypatch):
    def get(url, **kwargs):
        assert url == "http://connect.example.test/__api__/server_settings"
        assert "headers" not in kwargs
        return httpx.Response({status})
    monkeypatch.setattr(httpx, "get", get)
""")
    result = suite.runpytest_subprocess(
        "--vip-config=vip.toml",
        "-k",
        "Connect",
        "-o",
        "addopts=",
    )
    if status == 200:
        result.assert_outcomes(passed=1)
    else:
        result.assert_outcomes(failed=1)


def test_explicit_connect_client_still_requires_authentication(cleanup_suite):
    suite = cleanup_suite
    with (suite.path / "conftest.py").open("a", encoding="utf-8") as conftest:
        conftest.write("""
import vip.fixtures

# Avoid the URL-scheme probe; this test checks credential validation, not HTTP.
vip.fixtures.resolve_url_scheme = lambda config, **kwargs: config.url
""")
    suite.makepyfile("""
def test_api_check(connect_client):
    raise AssertionError("An unauthenticated API check must not reach its body")
""")
    result = suite.runpytest_subprocess("--vip-config=vip.toml", "-o", "addopts=")
    result.assert_outcomes(errors=1)
    assert "Connect API key is not configured" in result.stdout.str()


@pytest.mark.parametrize("auth", ["api_key", "client_auth"])
@pytest.mark.parametrize("test_fails", [False, True])
def test_authenticated_content_is_cleaned_before_client_closes(cleanup_suite, auth, test_fails):
    suite = cleanup_suite
    with (suite.path / "vip.toml").open("a", encoding="utf-8") as config:
        config.write(
            '\napi_key = "selftest-key"\n' if auth == "api_key" else '\n[auth]\nidp = "selftest"\n'
        )
    with (suite.path / "conftest.py").open("a", encoding="utf-8") as conftest:
        conftest.write("""
from pathlib import Path
from vip.client_auth import register_client_auth
import httpx

register_client_auth("selftest", lambda *args: httpx.BasicAuth("user", "password"))

def record(event):
    with Path("cleanup.log").open("a", encoding="utf-8") as log:
        log.write(event + "\\n")

@pytest.fixture(scope="session")
def connect_client():
    class Client:
        def cleanup_content(self, guids):
            assert guids == ["created-guid"]
            record("delete content")
        def cleanup_vip_content(self):
            record("sweep tagged content")
    yield Client()
    record("close client")
""")
    suite.makepyfile(f"""
def test_creates_content(_connect_created_guids):
    _connect_created_guids.append("created-guid")
    assert not {test_fails}
""")
    result = suite.runpytest_subprocess("--vip-config=vip.toml", "-o", "addopts=")
    result.assert_outcomes(failed=1) if test_fails else result.assert_outcomes(passed=1)
    assert (suite.path / "cleanup.log").read_text(encoding="utf-8").splitlines() == [
        "delete content",
        "delete content",
        "sweep tagged content",
        "close client",
    ]
