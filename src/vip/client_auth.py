"""Pluggable HTTP-client authentication registry.

VIP's product API clients (``ConnectClient``, ``WorkbenchClient``,
``PackageManagerClient``) normally authenticate with a static product
credential — a Connect API key, a Package Manager token, etc.  Some
deployments front the products with an external authenticator that needs a
different, possibly per-request or per-host, scheme that a single static
``Authorization`` header cannot express.

The motivating case is a Snowflake Native App, where each product sits behind
a Snowpark Container Services ingress that expects a short-lived
``Authorization: Snowflake Token="..."`` header derived per host via a JWT
token exchange.  Rather than teach VIP about Snowflake, this registry lets a
downstream extension register an :class:`httpx.Auth` factory keyed by IdP
name.  The product-client fixtures consult the registry and inject the
returned auth into the client.

Downstream usage (e.g. from an extension ``conftest.py``):

    from vip.client_auth import register_client_auth

    def _snowflake_auth(config, product, base_url):
        return MySnowflakeHttpxAuth(...)

    register_client_auth("snowflake", _snowflake_auth)

The registry is keyed by the configured ``[auth] idp`` value, so the same IdP
name selects both the browser login strategy (:mod:`vip.idp`) and the HTTP
client auth.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from vip.config import VIPConfig

# A factory receives the loaded config, the product name ("connect",
# "workbench", "package_manager") and that product's base URL, and returns an
# ``httpx.Auth`` to use for the client — or ``None`` to fall back to the
# default static-credential behaviour.
ClientAuthFactory = Callable[["VIPConfig", str, str], "httpx.Auth | None"]

_CLIENT_AUTH_FACTORIES: dict[str, ClientAuthFactory] = {}


def register_client_auth(idp: str, factory: ClientAuthFactory) -> None:
    """Register an :class:`httpx.Auth` *factory* for the given *idp* name.

    The *idp* value is normalized (stripped, lowercased).  Re-registering an
    IdP replaces the previous factory.
    """
    _CLIENT_AUTH_FACTORIES[idp.strip().lower()] = factory


def get_client_auth_factory(idp: str) -> ClientAuthFactory | None:
    """Return the registered factory for *idp*, or ``None`` if unregistered."""
    return _CLIENT_AUTH_FACTORIES.get(idp.strip().lower())


def build_client_auth(config: VIPConfig, product: str, base_url: str) -> httpx.Auth | None:
    """Build an :class:`httpx.Auth` for *product* from the registered factory.

    Looks up the factory for the configured ``[auth] idp`` and invokes it.
    Returns ``None`` when no IdP is configured, no factory is registered for
    it, or the factory itself returns ``None`` — in which case clients use
    their default static-credential auth.
    """
    idp = (config.auth.idp or "").strip().lower()
    if not idp:
        return None
    factory = _CLIENT_AUTH_FACTORIES.get(idp)
    if factory is None:
        return None
    return factory(config, product, base_url)
