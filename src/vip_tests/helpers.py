"""Shared test helper functions used across product test modules."""

from __future__ import annotations

import re
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

import httpx

# Patterns to extract host and port from common database connection strings.
# Supports jdbc:, postgresql://, mysql://, mssql://, etc.
_DB_HOST_PORT_RE = re.compile(
    r"(?:jdbc:[a-z]+://|[a-z]+://)"  # scheme (including jdbc: prefix)
    r"(?:[^@]*@)?"  # optional user:pass@
    r"([^/:@?]+)"  # host
    r"(?::(\d+))?",  # optional :port
    re.IGNORECASE,
)

# Well-known default ports for common DB types.
_DEFAULT_PORTS: dict[str, int] = {
    "postgresql": 5432,
    "postgres": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "mssql": 1433,
    "sqlserver": 1433,
    "oracle": 1521,
    "redshift": 5439,
    "bigquery": 443,
    "snowflake": 443,
}

_TCP_TIMEOUT = 5  # seconds


def _tcp_reachable(host: str, port: int, timeout: float = _TCP_TIMEOUT) -> tuple[bool, str | None]:
    """Return (True, None) if a TCP connection to host:port succeeds within *timeout* seconds.

    Returns (False, error_message) otherwise.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except OSError as exc:
        return False, str(exc)


def _extract_host_port(connection_string: str, ds_type: str) -> tuple[str, int] | None:
    """Extract (host, port) from a database connection string.

    Returns None if the host cannot be determined (e.g. embedded SQLite path).
    """
    match = _DB_HOST_PORT_RE.search(connection_string)
    if not match:
        return None
    host = match.group(1)
    raw_port = match.group(2)
    if raw_port:
        port = int(raw_port)
    else:
        # Fall back to well-known defaults keyed by DS type.
        port = _DEFAULT_PORTS.get(ds_type.lower(), 0)
    if not host or port == 0:
        return None
    return host, port


def check_data_source_connectivity(data_sources, verify: bool | str = True) -> list[dict]:
    """Test connectivity to each configured data source.

    For HTTP/API sources, attempts a real HTTP GET and checks the response
    status code.

    For database sources, VIP does not install DB drivers, so a full
    client-level handshake is not possible.  Instead, we attempt a TCP
    socket connection to the host and port extracted from the connection
    string.  This confirms that the server is reachable from the test
    runner (correct network path, firewall rules, DNS resolution), which
    is the meaningful check we can perform without DB drivers.

    If the host/port cannot be parsed from the connection string, we fall
    back to verifying that the connection string is non-empty and add a
    note in the error field explaining the limitation.

    Args:
        data_sources: Sequence of DataSourceEntry objects from vip_config.

    Returns:
        List of result dicts, each with keys: name, type, ok, error.
    """
    results = []
    for ds in data_sources:
        result = {"name": ds.name, "type": ds.type, "ok": False, "error": None}
        try:
            if ds.type in ("http", "api"):
                # `verify` controls TLS certificate validation for HTTP sources.
                # Non-HTTP types (DB, TCP) use socket.create_connection and do
                # not perform TLS; the verify parameter is intentionally ignored
                # for those types.
                resp = httpx.get(ds.connection_string, timeout=15, verify=verify)
                result["ok"] = resp.status_code < 400
            else:
                if not ds.connection_string:
                    result["error"] = "connection_string is empty"
                else:
                    host_port = _extract_host_port(ds.connection_string, ds.type)
                    if host_port is not None:
                        host, port = host_port
                        reachable, err = _tcp_reachable(host, port)
                        result["ok"] = reachable
                        if not reachable:
                            result["error"] = f"TCP connect to {host}:{port} failed: {err}"
                    else:
                        # Cannot parse host:port (e.g. embedded DB or unusual
                        # connection string format).  Record config presence as
                        # the only available signal and document the limitation.
                        result["ok"] = True
                        result["error"] = (
                            "Could not parse host:port from connection string; "
                            "only config presence was verified (no TCP check possible)."
                        )
        except Exception as exc:
            result["error"] = str(exc)
        results.append(result)
    return results


def _split_case_insensitive_prefix(url: str) -> tuple[str, str] | None:
    """Split *url* into a lowercased `scheme://host` prefix and its exact-case path.

    Scheme and host are case-insensitive per RFC 3986; the path is not, so the
    two halves are kept separate rather than lowercasing the whole URL, which
    would turn a real path-case mismatch (e.g. /CRAN/latest vs /cran/latest)
    into a false match. Returns None when *url* carries no scheme/host to
    split on (e.g. a scheme-less URL that was never resolved), so callers can
    fall back to a plain string comparison instead of guessing one.
    """
    parts = urlsplit(url.rstrip("/"))
    if not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower(), parts.path


# Characters that cannot be part of a URL as embedded in VIP's own log/output
# text -- mirrors the charset excluded by the `https?://[^\s<>"']+` extraction
# regex used elsewhere (e.g. `vip_tests.workbench.conftest.extract_repo_urls`).
# A match ending on anything else (e.g. the "foo" in ".../latestfoo") means the
# expected path was only a prefix of a longer token, not the whole URL.
_URL_BOUNDARY_CHARS = frozenset(" \t\n\r\v\f<>\"'/?#")


def _ends_at_url_boundary(line: str, end: int) -> bool:
    """True when position *end* in *line* is the end of a URL, not its middle."""
    return end >= len(line) or line[end] in _URL_BOUNDARY_CHARS


def pm_url_in_log_lines(pm_url: str, output_lines: Iterable[str]) -> bool:
    """True when `pm_url` appears in any log line.

    Scheme and host compare case-insensitively; the path compares exactly.
    See `_split_case_insensitive_prefix` for why. The match must also end at
    a URL boundary (end of string, `/`, `?`, `#`, or a delimiter that could
    not be part of a URL) -- otherwise "/cran/latest" would match inside
    "/cran/latestfoo", which is a different, longer path that happens to
    share a prefix. Note this compares against the path only, not any query
    string, since Package Manager repo URLs don't carry one in practice.
    """
    normalized = _split_case_insensitive_prefix(pm_url)
    if normalized is None:
        # No scheme/host to split on -- fall back to an exact substring test.
        needle = pm_url.rstrip("/")
        return any(needle in line for line in output_lines)

    prefix, path = normalized

    for line in output_lines:
        lowered = line.lower()
        start = 0
        while True:
            idx = lowered.find(prefix, start)
            if idx == -1:
                break
            tail = idx + len(prefix)
            end = tail + len(path)
            if line[tail:end] == path and _ends_at_url_boundary(line, end):
                return True
            start = idx + 1
    return False


def pm_url_matches_repo_urls(pm_url: str, repo_urls: Iterable[str]) -> bool:
    """True when `pm_url` exactly matches, or is an exact ancestor path of, any URL in `repo_urls`.

    Scheme and host compare case-insensitively; the path compares exactly
    (see `_split_case_insensitive_prefix`). A trailing "/" boundary on the
    path distinguishes a real sub-path match -- e.g. `pm_url` "https://pm/cran"
    matching "https://pm/cran/latest" -- from a same-prefix but unrelated path
    like "https://pm/cranfoo".
    """
    normalized = _split_case_insensitive_prefix(pm_url)
    if normalized is None:
        # No scheme/host to split on -- fall back to the original exact/prefix
        # string comparison rather than guessing a scheme.
        needle = pm_url.rstrip("/")
        return any(url.rstrip("/") == needle or url.startswith(needle + "/") for url in repo_urls)

    expected_prefix, expected_path = normalized

    for url in repo_urls:
        candidate = _split_case_insensitive_prefix(url)
        if candidate is None:
            continue
        candidate_prefix, candidate_path = candidate
        if candidate_prefix != expected_prefix:
            continue
        if candidate_path == expected_path or candidate_path.startswith(expected_path + "/"):
            return True
    return False
