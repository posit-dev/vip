"""Pluggable load test driver with multiple backends.

Supports three backends for concurrent HTTP load generation:

- **threadpool**: ``ThreadPoolExecutor`` (default for ≤100 users, no extra deps)
- **async**: ``asyncio`` + ``httpx.AsyncClient`` (default for >100 users, no extra deps)
- **locust**: headless Locust ``Environment`` (optional, requires ``vip[load]``)

The :func:`run_load_test` entry point routes to the appropriate backend based
on the ``load_test_tool`` field in :class:`~vip.config.PerformanceConfig`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from vip.config import PerformanceConfig


@dataclass
class LoadTestResult:
    """Aggregate results from a load test run."""

    total: int
    successes: int
    failure_rate: float
    p95_response_time: float
    results: list[dict] = field(repr=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_load_test(
    url: str,
    headers: dict[str, str],
    users: int,
    config: PerformanceConfig,
) -> LoadTestResult:
    """Run a load test and return aggregated results.

    The backend is selected by ``config.load_test_tool``:

    - ``"auto"`` (default): threadpool for ≤100, async for >100
    - ``"threadpool"``: always use ThreadPoolExecutor
    - ``"async"``: always use asyncio + httpx.AsyncClient
    - ``"locust"``: use headless Locust (requires ``vip[load]``)
    """
    tool = config.load_test_tool

    if tool == "locust":
        # Locust returns LoadTestResult directly (aggregate stats, no raw data).
        return _run_locust(url, headers, users, config)
    elif tool == "threadpool" or (tool == "auto" and users <= 100):
        raw = _run_threadpool(url, headers, users)
    elif tool == "async" or (tool == "auto" and users > 100):
        raw = _run_async(url, headers, users, max_connections=config.load_max_connections)
    else:
        msg = f"Unknown load_test_tool: {tool!r}"
        raise ValueError(msg)

    return _build_result(raw)


# ---------------------------------------------------------------------------
# Threadpool backend
# ---------------------------------------------------------------------------


def _run_threadpool(url: str, headers: dict[str, str], n: int, timeout: float = 30.0) -> list[dict]:
    """Fire *n* synchronous GET requests via a thread pool.

    Each thread creates its own request via ``httpx.get()`` (which uses a
    fresh transport per call) because ``httpx.Client`` is not thread-safe.
    """

    def _fetch():
        start = time.monotonic()
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
            return {
                "elapsed": time.monotonic() - start,
                "status": resp.status_code,
                "error": None,
            }
        except Exception as exc:
            return {
                "elapsed": time.monotonic() - start,
                "status": None,
                "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=min(n, 500)) as pool:
        futures = [pool.submit(_fetch) for _ in range(n)]
        return [f.result() for f in as_completed(futures)]


# ---------------------------------------------------------------------------
# Async httpx backend
# ---------------------------------------------------------------------------


def _run_async(
    url: str,
    headers: dict[str, str],
    n: int,
    max_connections: int = 200,
    timeout: float = 30.0,
) -> list[dict]:
    """Fire *n* async GET requests with bounded concurrency."""
    return asyncio.run(_async_load_test(url, headers, n, max_connections, timeout))


async def _async_load_test(
    url: str,
    headers: dict[str, str],
    n: int,
    max_connections: int,
    timeout: float,
) -> list[dict]:
    semaphore = asyncio.Semaphore(max_connections)
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_connections,
    )

    async with httpx.AsyncClient(headers=headers, limits=limits, timeout=timeout) as client:

        async def _fetch():
            async with semaphore:
                start = time.monotonic()
                try:
                    resp = await client.get(url)
                    return {
                        "elapsed": time.monotonic() - start,
                        "status": resp.status_code,
                        "error": None,
                    }
                except Exception as exc:
                    return {
                        "elapsed": time.monotonic() - start,
                        "status": None,
                        "error": str(exc),
                    }

        tasks = [asyncio.create_task(_fetch()) for _ in range(n)]
        return list(await asyncio.gather(*tasks))


# ---------------------------------------------------------------------------
# Locust backend (optional)
# ---------------------------------------------------------------------------


def _locust_available() -> bool:
    """Return True if the ``locust`` package is importable."""
    return importlib.util.find_spec("locust") is not None


def _run_locust(url: str, headers: dict[str, str], n: int, config) -> LoadTestResult:
    """Run a headless Locust load test and return aggregated results."""
    if not _locust_available():
        msg = (
            f"locust not installed; {n} users with tool='locust' requires: "
            "pip install 'posit-vip[load]'"
        )
        raise RuntimeError(msg)

    # Parse base URL and path from the full URL.
    from urllib.parse import urlparse

    import gevent  # available when locust is installed
    from locust import HttpUser, constant, task
    from locust.env import Environment

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"

    # Capture headers in the class body for the Locust user.
    request_headers = dict(headers)

    class _VIPUser(HttpUser):
        host = base_url
        wait_time = constant(0)

        @task
        def check(self):
            self.client.get(path, headers=request_headers)

    env = Environment(user_classes=[_VIPUser])
    runner = env.create_local_runner()
    runner.start(n, spawn_rate=config.load_test_spawn_rate)
    gevent.sleep(config.load_test_duration)
    runner.stop()
    runner.quit()

    # Convert Locust stats to the common result format.
    stats = env.stats.total
    total = stats.num_requests
    if total == 0:
        return LoadTestResult(
            total=0, successes=0, failure_rate=1.0, p95_response_time=0.0, results=[]
        )

    # Locust gives aggregate stats, not per-request data.  Build a
    # LoadTestResult directly to preserve the real p95.
    p95_s = (stats.get_response_time_percentile(0.95) or 0) / 1000.0
    successes = total - stats.num_failures
    failure_rate = 1.0 - (successes / total) if total else 1.0

    return LoadTestResult(
        total=total,
        successes=successes,
        failure_rate=failure_rate,
        p95_response_time=p95_s,
        results=[],  # no per-request data from locust
    )


# ---------------------------------------------------------------------------
# Repo classification
# ---------------------------------------------------------------------------


def classify_repos(repos: list[dict]) -> tuple[list[str], list[str]]:
    """Classify repos into ``(cran_repos, pypi_repos)`` by their type field.

    Accepts canonical API values (``"R"``, ``"Python"``) and common aliases
    (``"cran"``, ``"pypi"``), case-insensitively.  Repos with unknown or
    missing types are silently skipped.
    """
    cran: list[str] = []
    pypi: list[str] = []
    for repo in repos:
        name = repo.get("name", "")
        if not name:
            continue
        repo_type = str(repo.get("type", "")).strip().lower()
        if repo_type in ("r", "cran"):
            cran.append(name)
        elif repo_type in ("python", "pypi"):
            pypi.append(name)
    return cran, pypi


# ---------------------------------------------------------------------------
# User simulation (multi-endpoint, realistic behavior)
# ---------------------------------------------------------------------------


def _stderr(msg: str) -> None:
    """Write *msg* to stderr at the fd level, bypassing Python/gevent buffering."""
    try:
        fd = sys.stderr.fileno()
    except (AttributeError, io.UnsupportedOperation):
        fd = 2
    data = (msg + "\n").encode()
    while data:
        written = os.write(fd, data)
        data = data[written:]


def _log_request(
    request_type: str,
    name: str,
    response_time: float,
    response_length: int,
    exception: Exception | None = None,
    **_kwargs,
) -> None:
    """Print a single Locust request to stderr for ``--verbose`` diagnostics."""
    elapsed_s = (response_time or 0) / 1000.0
    if exception:
        _stderr(f"[locust] {request_type} {name} {elapsed_s:.2f}s FAIL {exception}")
    else:
        _stderr(f"[locust] {request_type} {name} {elapsed_s:.2f}s")


def run_user_simulation(
    host: str,
    user_class_name: str,
    users: int,
    config,
    *,
    credentials: dict[str, str] | None = None,
    verbose: bool = False,
) -> LoadTestResult:
    """Run a realistic user simulation using product-specific Locust user classes.

    Parameters
    ----------
    host:
        Base URL for the product (e.g. ``https://connect.example.com``).
    user_class_name:
        One of ``"connect"``, ``"workbench"``, ``"package_manager"``.
    users:
        Number of simulated concurrent users.
    config:
        :class:`~vip.config.PerformanceConfig` instance.
    credentials:
        Product-specific credentials passed to the user class via
        ``environment.parsed_options``.  Keys depend on the product
        (e.g. ``{"api_key": "..."}`` for Connect/Workbench,
        ``{"token": "..."}`` for Package Manager).
    """
    if not _locust_available():
        msg = "locust not installed; user simulation requires: pip install 'posit-vip[load]'"
        raise RuntimeError(msg)

    # Locust's import triggers gevent monkey.patch_all(), which deadlocks if
    # any threading.Thread instances are alive.  The VIP plugin's heartbeat
    # thread is running at this point, so stop it before importing.
    import vip.plugin as _plugin

    heartbeat = getattr(_plugin, "_current_heartbeat", None)
    if heartbeat is not None:
        heartbeat.stop()

    import gevent
    from locust.env import Environment

    from vip.load_users import ConnectUser, PackageManagerUser, WorkbenchUser

    user_classes = {
        "connect": ConnectUser,
        "workbench": WorkbenchUser,
        "package_manager": PackageManagerUser,
    }

    if user_class_name not in user_classes:
        msg = f"Unknown user class: {user_class_name!r}"
        raise ValueError(msg)

    # Create a concrete subclass with the correct host.
    base_class = user_classes[user_class_name]
    concrete = type(
        f"_{user_class_name}_user",
        (base_class,),
        {"host": host, "abstract": False},
    )

    # Pass credentials via a custom attribute on the environment.
    env = Environment(user_classes=[concrete])
    env._vip_credentials = credentials or {}  # type: ignore[attr-defined]
    if verbose:
        env.events.request.add_listener(_log_request)
        _stderr(
            f"[locust] starting {users} {user_class_name} users against {host} "
            f"for {config.load_test_duration}s"
        )
    runner = env.create_local_runner()
    runner.start(users, spawn_rate=config.load_test_spawn_rate)
    gevent.sleep(config.load_test_duration)
    if verbose:
        _stderr("[locust] duration elapsed, stopping runner...")
    runner.stop()
    if verbose:
        _stderr("[locust] runner stopped, quitting...")
    runner.quit()

    stats = env.stats.total
    total = stats.num_requests
    if total == 0:
        return LoadTestResult(
            total=0, successes=0, failure_rate=1.0, p95_response_time=0.0, results=[]
        )

    p95_s = (stats.get_response_time_percentile(0.95) or 0) / 1000.0
    successes = total - stats.num_failures
    failure_rate = 1.0 - (successes / total) if total else 1.0

    return LoadTestResult(
        total=total,
        successes=successes,
        failure_rate=failure_rate,
        p95_response_time=p95_s,
        results=[],
    )


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------


def _build_result(raw: list[dict]) -> LoadTestResult:
    """Construct a :class:`LoadTestResult` from raw per-request dicts."""
    total = len(raw)
    successes = sum(
        1 for r in raw if r["error"] is None and r["status"] is not None and r["status"] < 400
    )
    failure_rate = 1.0 - (successes / total) if total else 1.0

    elapsed = [r["elapsed"] for r in raw]
    if len(elapsed) < 2:
        p95 = elapsed[0] if elapsed else 0.0
    else:
        p95 = statistics.quantiles(elapsed, n=100, method="inclusive")[94]

    return LoadTestResult(
        total=total,
        successes=successes,
        failure_rate=failure_rate,
        p95_response_time=p95,
        results=raw,
    )
