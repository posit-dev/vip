"""Browser authentication run from ``pytest_configure``, and its xdist worker restore."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from vip.config import VIPConfig
from vip.stash import _auth_mode_key, _auth_session_key


def _configure_auth(config: pytest.Config, vip_cfg: VIPConfig) -> None:
    """Run the ``--interactive-auth``/``--headless-auth`` login for ``pytest_configure``."""
    # Handle interactive auth — login via browser, then close before tests.
    # With pytest-xdist the browser auth happens once in the controller;
    # credentials are forwarded to workers via pytest_configure_node.
    config.stash[_auth_session_key] = None

    if hasattr(config, "workerinput"):
        # xdist worker — restore auth data shared by the controller (if any).
        # Workers must never re-run the controller-only browser-auth branches
        # below: pytest_configure fires on every worker, so doing so would, for
        # example, re-emit the "no auth-requiring products" warning once per
        # worker, flooding the output.
        if config.workerinput.get("vip_interactive_auth"):
            _restore_worker_auth(config, vip_cfg)
        elif config.workerinput.get("vip_auth_mode"):
            # No browser session was forwarded (no auth-requiring product), but
            # still mirror the controller's auth mode so the auth_mode fixture
            # matches a non-xdist run.
            config.stash[_auth_mode_key] = config.workerinput["vip_auth_mode"]
    elif config.getoption("--interactive-auth"):
        config.stash[_auth_mode_key] = "interactive"
        connect_url = vip_cfg.connect.url if vip_cfg.connect.is_configured else None
        wb_url = vip_cfg.workbench.url if vip_cfg.workbench.is_configured else None

        if not connect_url and not wb_url:
            # No auth-requiring product is configured (e.g. only Package Manager).
            # Skip the browser flow entirely rather than erroring out.
            warnings.warn(
                "VIP: --interactive-auth was requested but no auth-requiring products "
                "(Connect, Workbench) are configured; skipping browser authentication.",
                stacklevel=1,
            )
        else:
            from vip.auth import AuthConfigError, auth_cache_path, start_interactive_auth

            cache_path = auth_cache_path()
            try:
                session = start_interactive_auth(
                    connect_url=connect_url,
                    workbench_url=wb_url,
                    cache_path=cache_path,
                    insecure=vip_cfg.insecure,
                    ca_bundle=vip_cfg.ca_bundle,
                    connect_url_scheme_inferred=vip_cfg.connect.url_scheme_inferred,
                    workbench_url_scheme_inferred=vip_cfg.workbench.url_scheme_inferred,
                    proxy=vip_cfg.proxy,
                )
            except AuthConfigError as exc:
                raise pytest.UsageError(str(exc)) from None
            config.stash[_auth_session_key] = session
            if session.api_key:
                vip_cfg.connect.api_key = session.api_key
            # Auth may have rewritten the Connect URL (sub-path dashboard +
            # root API, or an inferred https:// downgraded to http:// -- see
            # resolve_url_scheme).  Sync so the test clients hit the same
            # base mint/login did.
            if session._connect_url and connect_url and session._connect_url != connect_url:
                vip_cfg.connect.url = session._connect_url
            # Same sync for Workbench: an inferred https:// that resolve_url_scheme
            # downgraded to http:// must reach vip_cfg.workbench.url the same way,
            # not rely on conftest.py's fixture-level resolve_url_scheme call
            # hitting a cache entry keyed on the URL string as an unstated
            # side-channel (issue #562 comment-accuracy review).
            if session._workbench_url and wb_url and session._workbench_url != wb_url:
                vip_cfg.workbench.url = session._workbench_url
            if not session.api_key and connect_url:
                warnings.warn(
                    "VIP: --interactive-auth could not mint an API key. "
                    "API-based tests will likely fail. "
                    "Try again or set VIP_CONNECT_API_KEY to fix.",
                    stacklevel=1,
                )
    elif config.getoption("--headless-auth"):
        config.stash[_auth_mode_key] = "headless"
        connect_url = vip_cfg.connect.url if vip_cfg.connect.is_configured else None
        wb_url = vip_cfg.workbench.url if vip_cfg.workbench.is_configured else None

        if not connect_url and not wb_url:
            # No auth-requiring product is configured (e.g. only Package Manager).
            # Skip the browser flow entirely rather than erroring out.
            warnings.warn(
                "VIP: --headless-auth was requested but no auth-requiring products "
                "(Connect, Workbench) are configured; skipping browser authentication.",
                stacklevel=1,
            )
        else:
            from vip.auth import AuthConfigError, auth_cache_path, start_headless_auth

            cache_path = auth_cache_path()
            try:
                session = start_headless_auth(
                    connect_url=connect_url,
                    workbench_url=wb_url,
                    idp=vip_cfg.auth.idp,
                    provider=vip_cfg.auth.provider,
                    username=vip_cfg.auth.username,
                    password=vip_cfg.auth.password,
                    cache_path=cache_path,
                    verbose=config.getoption("--vip-verbose", default=False),
                    insecure=vip_cfg.insecure,
                    ca_bundle=vip_cfg.ca_bundle,
                    connect_url_scheme_inferred=vip_cfg.connect.url_scheme_inferred,
                    workbench_url_scheme_inferred=vip_cfg.workbench.url_scheme_inferred,
                    proxy=vip_cfg.proxy,
                )
            except AuthConfigError as exc:
                raise pytest.UsageError(str(exc)) from None
            config.stash[_auth_session_key] = session
            if session.api_key:
                vip_cfg.connect.api_key = session.api_key
            # Auth may have rewritten the Connect URL (sub-path dashboard +
            # root API, or an inferred https:// downgraded to http:// -- see
            # resolve_url_scheme).  Sync so the test clients hit the same
            # base mint/login did.
            if session._connect_url and connect_url and session._connect_url != connect_url:
                vip_cfg.connect.url = session._connect_url
            # Same sync for Workbench -- see the --interactive-auth branch above.
            if session._workbench_url and wb_url and session._workbench_url != wb_url:
                vip_cfg.workbench.url = session._workbench_url
            if not session.api_key and connect_url:
                warnings.warn(
                    "VIP: --headless-auth could not mint an API key. "
                    "API-based tests will likely fail. "
                    "Try again or set VIP_CONNECT_API_KEY to fix.",
                    stacklevel=1,
                )


def _restore_worker_auth(config: pytest.Config, vip_cfg: VIPConfig) -> None:
    """Reconstruct an auth session in an xdist worker from controller data."""
    from vip.auth import InteractiveAuthSession

    wi = config.workerinput  # type: ignore[attr-defined]  # xdist injects this
    api_key = wi.get("vip_api_key") or None
    storage_state = wi.get("vip_storage_state", "")
    connect_url = wi.get("vip_connect_url", "") or ""

    if api_key:
        vip_cfg.connect.api_key = api_key
    # Mirror the controller's URL rewrite (split sub-path dashboard + root
    # API).  Without this, workers build ConnectClient from the original
    # sub-path URL and 404 against /__api__/.
    if connect_url and vip_cfg.connect.is_configured and connect_url != vip_cfg.connect.url:
        vip_cfg.connect.url = connect_url

    session = InteractiveAuthSession(
        storage_state_path=Path(storage_state) if storage_state else Path("/dev/null"),
        api_key=api_key,
        key_name=wi.get("vip_key_name", ""),
        workbench_auth_error=wi.get("vip_workbench_auth_error") or None,
        _connect_url=connect_url,
        _workbench_url=wi.get("vip_workbench_url", "") or "",
        _tmpdir="",  # Workers don't own the temp dir; controller cleans up.
    )
    config.stash[_auth_session_key] = session
    mode = wi.get("vip_auth_mode")
    if mode:
        config.stash[_auth_mode_key] = mode
