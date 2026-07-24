"""Selftests for the JupyterLab notebook-cleanup helpers on WorkbenchClient.

These cover the pure URL/header builders and the ``delete_jupyter_notebook``
method (via an ``httpx.MockTransport``), so the contents-API teardown that keeps
JupyterLab sessions fresh is exercised without a live Workbench.
"""

from __future__ import annotations

import httpx
import pytest

from vip.clients.workbench import (
    WorkbenchClient,
    jupyterlab_app_base,
    jupyterlab_contents_delete_url,
    jupyterlab_xsrf_headers,
)

# -- jupyterlab_app_base -----------------------------------------------------


@pytest.mark.parametrize(
    "page_url, expected",
    [
        # Standard per-session proxy prefix, notebook open under /lab/tree.
        (
            "https://wb.example.com/s/abc123/lab/tree/Untitled.ipynb",
            "https://wb.example.com/s/abc123",
        ),
        # Bare /lab root.
        ("https://wb.example.com/s/abc123/lab", "https://wb.example.com/s/abc123"),
        # Query string and fragment are stripped.
        (
            "https://wb.example.com/s/xyz/lab/tree/Untitled1.ipynb?reset#cell",
            "https://wb.example.com/s/xyz",
        ),
        # No /lab segment — return the URL trimmed rather than raising.
        ("https://wb.example.com/s/abc123/", "https://wb.example.com/s/abc123"),
        # Real Workbench shape (validated live via CDP on pwb.demo): JupyterLab
        # inserts a /lab/workspaces/<id>/tree/<nb> segment. The base must still
        # cut at /lab and match PageConfig.baseUrl (".../s/<sid>").
        (
            "https://pwb.demo.soleng.posit.it/s/0da2921f2ed72297f2efa/lab/workspaces/auto-m/tree/Untitled7.ipynb",
            "https://pwb.demo.soleng.posit.it/s/0da2921f2ed72297f2efa",
        ),
    ],
)
def test_jupyterlab_app_base(page_url, expected):
    assert jupyterlab_app_base(page_url) == expected


# -- jupyterlab_contents_delete_url ------------------------------------------


def test_contents_delete_url_basic():
    url = jupyterlab_contents_delete_url(
        "https://wb.example.com/s/abc123/lab/tree/Untitled.ipynb", "Untitled.ipynb"
    )
    assert url == "https://wb.example.com/s/abc123/api/contents/Untitled.ipynb"


def test_contents_delete_url_quotes_spaces_and_strips_slashes():
    url = jupyterlab_contents_delete_url("https://wb.example.com/s/abc123/lab", "/_vip run 1.ipynb")
    # Leading slash stripped, space percent-encoded.
    assert url == "https://wb.example.com/s/abc123/api/contents/_vip%20run%201.ipynb"


# -- jupyterlab_xsrf_headers -------------------------------------------------


def test_xsrf_headers_present():
    assert jupyterlab_xsrf_headers({"_xsrf": "tok123"}) == {"X-XSRFToken": "tok123"}


def test_xsrf_headers_absent():
    assert jupyterlab_xsrf_headers({"other": "v"}) == {}


# -- delete_jupyter_notebook (MockTransport) ---------------------------------


def _client_with_handler(handler) -> WorkbenchClient:
    wc = WorkbenchClient("https://wb.example.com")
    wc._client.close()
    wc._client = httpx.Client(
        base_url="https://wb.example.com",
        transport=httpx.MockTransport(handler),
    )
    return wc


def test_delete_notebook_success_sends_xsrf_and_targets_contents_api():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["xsrf"] = request.headers.get("X-XSRFToken")
        return httpx.Response(204)

    wc = _client_with_handler(handler)
    ok = wc.delete_jupyter_notebook(
        "https://wb.example.com/s/abc123/lab/tree/Untitled.ipynb",
        "Untitled.ipynb",
        {"_xsrf": "tok123"},
    )
    assert ok is True
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/s/abc123/api/contents/Untitled.ipynb"
    assert seen["xsrf"] == "tok123"


def test_delete_notebook_404_treated_as_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    wc = _client_with_handler(handler)
    assert (
        wc.delete_jupyter_notebook("https://wb.example.com/s/abc/lab", "Untitled.ipynb", {}) is True
    )


def test_delete_notebook_server_error_is_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    wc = _client_with_handler(handler)
    assert (
        wc.delete_jupyter_notebook(
            "https://wb.example.com/s/abc/lab", "Untitled.ipynb", {"_xsrf": "t"}
        )
        is False
    )


def test_delete_notebook_transport_error_is_false():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert (
        wc.delete_jupyter_notebook("https://wb.example.com/s/abc/lab", "Untitled.ipynb", {})
        is False
    )
