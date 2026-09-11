import httpx
import pytest

from vip.clients.connect import ConnectClient


def _client(handler):
    c = ConnectClient(base_url="https://connect.example.com", api_key="k")
    c._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://connect.example.com"
    )
    return c


def test_list_audit_logs_returns_results():
    def handler(request):
        assert request.url.path == "/v1/audit_logs"
        return httpx.Response(200, json={"results": [{"user_id": 1, "time": "t"}]})

    assert _client(handler).list_audit_logs() == [{"user_id": 1, "time": "t"}]


@pytest.mark.parametrize("status", [403, 404])
def test_list_audit_logs_returns_none_when_unavailable(status):
    assert _client(lambda r: httpx.Response(status)).list_audit_logs() is None


def test_allowed_methods_parses_the_allow_header():
    handler = lambda r: httpx.Response(200, headers={"Allow": "GET, HEAD, OPTIONS"})  # noqa: E731
    assert _client(handler).audit_log_allowed_methods() == {"GET", "HEAD", "OPTIONS"}


def test_allowed_methods_returns_none_without_an_allow_header():
    assert _client(lambda r: httpx.Response(200)).audit_log_allowed_methods() is None


def test_allowed_methods_never_issues_a_mutating_request():
    """Regression guard for the non-destructive contract."""
    seen = []

    def handler(request):
        seen.append(request.method)
        return httpx.Response(200, headers={"Allow": "GET"})

    _client(handler).audit_log_allowed_methods()
    assert seen == ["OPTIONS"]


class _RecordingClient:
    """Stands in for httpx.Client so we can inspect how it was constructed.

    unauthenticated_status builds its own client rather than using
    self._client, so MockTransport on the pooled client cannot see it.
    """

    instances: list["_RecordingClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requested = None
        _RecordingClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        self.requested = url
        return httpx.Response(401, request=httpx.Request("GET", url))


@pytest.fixture
def recording_client(monkeypatch):
    """Build a ConnectClient, THEN patch httpx.Client. Order is load-bearing.

    BaseClient.__init__ builds its own pooled httpx.Client (`base.py:135`).
    Patching before construction would make instances[0] the pooled client --
    which legitimately does carry credentials -- so every assertion below
    would inspect the wrong object and the credential test would pass or fail
    for entirely the wrong reason.
    """

    def _make(**kwargs):
        client = ConnectClient(base_url="https://connect.example.com", **kwargs)
        _RecordingClient.instances = []
        monkeypatch.setattr(httpx, "Client", _RecordingClient)
        return client

    return _make


def test_unauthenticated_status_returns_the_status(recording_client):
    c = recording_client(api_key="k")
    assert c.unauthenticated_status("/__api__/v1/users") == 401
    # Exactly one client was built, and it is the ad-hoc one.
    assert len(_RecordingClient.instances) == 1
    assert _RecordingClient.instances[0].requested == (
        "https://connect.example.com/__api__/v1/users"
    )


def test_unauthenticated_status_sends_no_credentials(recording_client):
    """The whole point of the method: an authorised caller would get 200."""
    c = recording_client(api_key="SECRET_KEY")
    c.unauthenticated_status("/__api__/v1/users")

    kwargs = _RecordingClient.instances[0].kwargs
    # No auth, no cookies, and no headers carrying the key were configured.
    assert "auth" not in kwargs or kwargs["auth"] is None
    assert not kwargs.get("cookies")
    assert "SECRET_KEY" not in repr(kwargs.get("headers", {}))


def test_unauthenticated_status_accepts_a_path_without_a_leading_slash(recording_client):
    """The two endpoints are customer-overridable in the Part 11 example's conftest.

    Someone editing that override writes `__api__/v1/users` as readily as
    `/__api__/v1/users`. Without normalization the two concatenate into
    `https://connect.example.com__api__/v1/users`, which is a different host,
    so the scenario fails on a deployment that is fine.
    """
    c = recording_client(api_key="k")
    assert c.unauthenticated_status("__api__/v1/users") == 401
    assert _RecordingClient.instances[0].requested == (
        "https://connect.example.com/__api__/v1/users"
    )


def test_unauthenticated_status_uses_the_configured_timeout(recording_client):
    """The ad-hoc client must not fall back to httpx's own default.

    BaseClient scales its default timeout, and a caller can override it; a probe
    that ignores both hangs for a different length of time than every other
    request the same client makes.
    """
    c = recording_client(api_key="k", timeout=7.5)
    c.unauthenticated_status("/__api__/v1/users")
    assert _RecordingClient.instances[0].kwargs["timeout"] == 7.5
    assert _RecordingClient.instances[0].kwargs["timeout"] == c._timeout


def test_unauthenticated_status_pins_trust_env_and_keeps_env_ca(recording_client):
    """trust_env=False also disables SSL_CERT_FILE; verify_with_env_ca restores it.

    verify_with_env_ca(True) returns a fresh ssl.SSLContext per call (via
    httpx.create_ssl_context), and SSLContext has no __eq__, so two contexts
    built from identical inputs are never `==`. Compare type instead of value.
    """
    from vip.proxy import verify_with_env_ca

    c = recording_client(api_key="k")
    c.unauthenticated_status("/__api__/v1/users")

    kwargs = _RecordingClient.instances[0].kwargs
    assert kwargs["trust_env"] is False
    assert type(kwargs["verify"]) is type(verify_with_env_ca(c._verify))
    assert "proxy" in kwargs
