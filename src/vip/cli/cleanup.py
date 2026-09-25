"""``vip cleanup``: remove VIP-created Connect content and Workbench sessions."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from vip.auth import (
    AuthConfigError,
    auth_cache_path,
    authenticated_page,
    resolve_url_scheme,
    start_headless_auth,
    start_interactive_auth,
)
from vip.cli._common import _resolve_effective_ca_bundle
from vip.clients.connect import ConnectClient
from vip.clients.workbench import WorkbenchClient
from vip.config import ProductConfig, VIPConfig, load_config
from vip.errors import (
    AuthError,
    ConfigError,
    ProductUnreachableError,
)
from vip.workbench_ui import quit_vip_sessions_via_ui


def _cleanup_workbench_sessions(
    workbench_url: str,
    _args: argparse.Namespace,
    config: VIPConfig,
) -> None:
    """Authenticate to Workbench and quit orphaned VIP-named sessions.

    API-first: quits via :meth:`~vip.clients.workbench.WorkbenchClient.quit_vip_sessions`
    when the session API is reachable. Escalates to a browser-driven UI sweep
    (:func:`vip.workbench_ui.quit_vip_sessions_via_ui`) when the API is
    unreachable *or* VIP sessions remain after the API sweep — a reachable API
    whose DELETE/suspend call is a silent no-op is exactly the #467 bug, so a
    "no error" response is not trusted on its own.

    Authentication is cache-aware: reuses a storage state saved by a prior
    ``vip verify`` run (same cache path, <4h old) when available. Uses
    ``--headless-auth``'s flow when ``VIP_TEST_USERNAME``/``VIP_TEST_PASSWORD``
    are set, otherwise opens an interactive browser login. Never lets an
    authentication failure crash with a bare traceback — prints an actionable
    error and exits 1.
    """
    insecure = config.insecure
    ca_bundle = config.ca_bundle
    proxy = config.proxy
    # Same helper plugin/auth.py uses, so this finds the session a prior `vip verify`
    # from this directory cached.
    cache_path = auth_cache_path()

    username = config.auth.username
    password = config.auth.password

    try:
        if username and password:
            session = start_headless_auth(
                workbench_url=workbench_url,
                provider=config.auth.provider,
                username=username,
                password=password,
                idp=config.auth.idp,
                cache_path=cache_path,
                insecure=insecure,
                ca_bundle=ca_bundle,
                proxy=proxy,
            )
        else:
            session = start_interactive_auth(
                workbench_url=workbench_url,
                cache_path=cache_path,
                insecure=insecure,
                ca_bundle=ca_bundle,
                proxy=proxy,
            )
    except AuthConfigError as exc:
        raise AuthError(f"could not authenticate to Workbench: {exc}") from exc
    except Exception as exc:
        raise AuthError(
            f"could not authenticate to Workbench at {workbench_url}: {exc}\n"
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD for non-interactive cleanup, "
            "or run this command where a browser can open for an interactive login."
        ) from exc

    try:
        print(f"Cleaning up orphaned Workbench sessions at {workbench_url}")
        cookies = session.load_cookies()
        client = WorkbenchClient(
            workbench_url, cookies=cookies, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
        )
        try:
            # sessions_api_reachable/count_vip_sessions currently signal an
            # unreachable API via their return value (False/-1), never a raise --
            # but a ProductUnreachableError is caught here too so this still
            # escalates to the UI sweep instead of aborting the whole command if
            # a future client change (errors-narrow-clients) starts raising it.
            try:
                api_reachable = client.sessions_api_reachable()
            except ProductUnreachableError:
                api_reachable = False
            if api_reachable:
                quit_count = client.quit_vip_sessions()
                print(f"Quit {quit_count} VIP Workbench session(s) via the API")
                try:
                    remaining = client.count_vip_sessions()
                except ProductUnreachableError:
                    remaining = -1
            else:
                remaining = -1  # unknown — escalate below

            # Escalate when the API is unreachable, when VIP sessions remain, or
            # when the count is undeterminable (-1). Only a confirmed 0 skips the
            # UI sweep, so an unparseable API response can never silently orphan
            # sessions (issue #467).
            if not api_reachable or remaining != 0:
                print("Escalating to browser-driven session cleanup ...")
                with authenticated_page(
                    session, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
                ) as page:
                    ui_count = quit_vip_sessions_via_ui(page, workbench_url)
                print(f"Quit {ui_count} VIP Workbench session(s) via the UI")
        finally:
            client.close()
    finally:
        session.cleanup()


def _ensure_cli_logging() -> None:
    """Route ``vip.*`` INFO/WARNING logs to stderr for the cleanup command.

    The session-cleanup path (WorkbenchClient + workbench_ui) emits progress
    and "sessions still present" warnings via ``logging``; without a handler
    those are invisible (or only WARNING via the lastResort handler). Attach a
    single stderr handler to the ``vip`` logger so ``vip cleanup`` surfaces
    what it did. Idempotent: only configures once.
    """
    vip_logger = logging.getLogger("vip")
    if not vip_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        vip_logger.addHandler(handler)
        vip_logger.setLevel(logging.INFO)
        vip_logger.propagate = False


def _load_cleanup_config(args: argparse.Namespace) -> VIPConfig:
    """Load ``vip.toml`` if present, else a default ``VIPConfig``.

    ``load_config`` warns when no config file exists, which is noise for
    ``vip cleanup`` when the user passes URLs explicitly and has no
    ``vip.toml``. This loads the file only when it actually exists; otherwise
    it returns a default ``VIPConfig`` whose ``__post_init__`` still picks up
    env-based credentials (``VIP_TEST_USERNAME``/``VIP_TEST_PASSWORD``,
    ``VIP_WORKBENCH_API_KEY``, etc.).

    ``--insecure``/``--ca-bundle`` win over the corresponding ``[tls]`` value
    already on the returned config, mirroring how a CLI ``--connect-url``
    wins over ``[connect] url`` elsewhere in this command -- and letting the
    flags work standalone with no ``vip.toml`` at all, which is the case
    issue #563 calls out as having nowhere else to put them. The merged pair
    still goes through ``_resolve_effective_ca_bundle`` so ``--insecure`` and
    ``[tls] insecure`` both take the same precedence over a bundle as ``verify``.
    """
    env = os.environ.get("VIP_CONFIG")
    path = Path(env) if env else Path("vip.toml")
    config = load_config() if path.exists() else VIPConfig()

    config.insecure = getattr(args, "insecure", False) or config.insecure
    config.ca_bundle = getattr(args, "ca_bundle", None) or config.ca_bundle
    config.ca_bundle = _resolve_effective_ca_bundle(config.insecure, config.ca_bundle)
    return config


def run_cleanup(args: argparse.Namespace) -> None:
    """Delete VIP test content from Connect and quit orphaned Workbench sessions.

    Connect cleanup deletes all content tagged ``_vip_test``. Workbench
    cleanup quits VIP-named sessions (see
    :func:`vip.clients.workbench.is_vip_session`), escalating to a
    browser-driven UI sweep when the session API is unreachable or sessions
    persist despite the API reporting success. The Connect/Workbench URLs
    come from ``--connect-url``/``--workbench-url`` or, if omitted, from
    ``[connect] url``/``[workbench] url`` in ``vip.toml``. At least one of
    the two must resolve. A scheme-less URL defaults to ``https://`` and
    falls back to ``http://`` if https doesn't answer (see
    ``vip.config._normalize_url`` / ``vip.auth.resolve_url_scheme``).
    """
    _ensure_cli_logging()

    connect_arg = getattr(args, "connect_url", None)
    api_key = getattr(args, "api_key", None) or os.environ.get("VIP_CONNECT_API_KEY", "")
    workbench_arg = getattr(args, "workbench_url", None)

    # Load vip.toml when present to fill in any URL not passed on the CLI, and
    # to supply TLS/auth settings for the Workbench path. Loaded quietly: an
    # explicit `vip cleanup --connect-url ...` with no vip.toml must not emit a
    # "Config file not found" warning (env-based credentials still apply).
    config = _load_cleanup_config(args)

    # A CLI flag wins over vip.toml. Wrapping the CLI arg in ProductConfig
    # routes it through the same _normalize_url a bare hostname gets from
    # every other entry point (vip verify, vip status), so ConnectClient
    # never receives a scheme-less URL -- httpx requires an absolute one --
    # and the probe-and-fallback treatment below still applies.
    # config.connect/config.workbench are already normalized ProductConfig
    # instances -- every ProductConfig runs _normalize_url in its own
    # __post_init__ regardless of how it was constructed, including the bare
    # VIPConfig() that _load_cleanup_config() returns when no vip.toml exists
    # -- so the vip.toml path needs no wrapping here.
    connect_pc: ProductConfig = ProductConfig(url=connect_arg) if connect_arg else config.connect
    workbench_pc: ProductConfig = (
        ProductConfig(url=workbench_arg) if workbench_arg else config.workbench
    )

    if not connect_pc.url and not workbench_pc.url:
        raise ConfigError(
            "no Connect or Workbench URL found. Pass --connect-url / "
            "--workbench-url, or set [connect] url / [workbench] url in vip.toml."
        )

    if connect_pc.url:
        connect_url = resolve_url_scheme(
            connect_pc, insecure=config.insecure, ca_bundle=config.ca_bundle, proxy=config.proxy
        )
        print(f"Cleaning up VIP test content on Connect at {connect_url}")
        with ConnectClient(
            connect_url,
            api_key,
            insecure=config.insecure,
            ca_bundle=config.ca_bundle,
            proxy=config.proxy,
        ) as client:
            deleted = client.cleanup_vip_content()
        print(f"Deleted {deleted} VIP test content item(s)")

    if workbench_pc.url:
        workbench_url = resolve_url_scheme(
            workbench_pc, insecure=config.insecure, ca_bundle=config.ca_bundle, proxy=config.proxy
        )
        _cleanup_workbench_sessions(workbench_url, args, config)

    print("Cleanup completed successfully")
