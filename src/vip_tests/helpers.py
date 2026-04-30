"""Shared test helper functions used across product test modules."""

from __future__ import annotations

import re
import socket

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
