"""Interactive browser authentication for OIDC providers.

Opens a headed Chromium browser for the user to complete an OIDC login
flow, mints a temporary Connect API key by calling the Connect REST API
with the browser's session cookies, saves the browser storage state, then
closes the browser before tests start.

The package namespace re-exports every name imported from ``vip.auth``.
Patch a helper on the submodule that calls it, not here: a re-export does
not change the global the submodule looks up.
"""

from vip.auth.apikey import _create_api_key_via_session, _resolve_connect_api_base
from vip.auth.browser import InteractiveAuthSession, _launch_chromium, authenticated_page
from vip.auth.cache import (
    _cached_workbench_session_is_live,
    _cookies_from_storage_state,
    _load_cached_auth,
    _ProbeResult,
    _save_auth_cache,
    auth_cache_path,
    refresh_auth_cache_from_storage_state,
)
from vip.auth.flows import start_headless_auth, start_interactive_auth
from vip.auth.scheme import _httpx_verify, _scheme_resolution_cache, resolve_url_scheme
from vip.auth.sso import _wait_for_product_redirect
from vip.auth.workbench import _authenticate_workbench, _click_workbench_oidc_confirm
from vip.errors import AuthConfigError, AuthTimeoutError

__all__ = [
    "AuthConfigError",
    "AuthTimeoutError",
    "InteractiveAuthSession",
    "_ProbeResult",
    "_authenticate_workbench",
    "_cached_workbench_session_is_live",
    "_click_workbench_oidc_confirm",
    "_cookies_from_storage_state",
    "_create_api_key_via_session",
    "_httpx_verify",
    "_launch_chromium",
    "_load_cached_auth",
    "_resolve_connect_api_base",
    "_save_auth_cache",
    "_scheme_resolution_cache",
    "_wait_for_product_redirect",
    "auth_cache_path",
    "authenticated_page",
    "refresh_auth_cache_from_storage_state",
    "resolve_url_scheme",
    "start_headless_auth",
    "start_interactive_auth",
]
