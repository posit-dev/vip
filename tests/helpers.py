"""Shared test helper functions used across product test modules."""

from __future__ import annotations

import httpx


def check_data_source_connectivity(data_sources) -> list[dict]:
    """Test connectivity to each configured data source.

    For HTTP/API sources, attempts a real HTTP GET and checks the response status.
    For database sources, verifies that the connection string is non-empty (a full
    connectivity check would require DB drivers that VIP does not mandate).

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
                resp = httpx.get(ds.connection_string, timeout=15)
                result["ok"] = resp.status_code < 400
            else:
                # For database types, verify the connection string is non-empty.
                # A full connectivity check requires DB drivers that we don't
                # want to mandate.
                result["ok"] = bool(ds.connection_string)
                if not result["ok"]:
                    result["error"] = "connection_string is empty"
        except Exception as exc:
            result["error"] = str(exc)
        results.append(result)
    return results
