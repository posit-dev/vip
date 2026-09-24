"""``vip status``: product health checks."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vip.config import VIPConfig


def _collect_status(config: VIPConfig) -> dict:
    """Run health checks and return structured status data.

    Returns a dict with the schema::

        {
            "products": {
                "connect":         {"configured": bool, "state": "ok"|"fail"|"skip", ...},
                "workbench":       {...},
                "package_manager": {...},
            },
            "outcome": "ok" | "fail",
            "exit_status": 0 | 1,
        }

    No printing or sys.exit side effects; callers handle rendering.
    """
    from vip.clients.connect import ConnectClient
    from vip.clients.packagemanager import PackageManagerClient
    from vip.clients.workbench import WorkbenchClient

    checks = [
        ("connect", config.connect),
        ("workbench", config.workbench),
        ("package_manager", config.package_manager),
    ]

    products: dict[str, dict] = {}
    for name, pc in checks:
        if not pc.is_configured:
            products[name] = {"configured": False, "state": "skip", "detail": "not configured"}
            continue
        try:
            from vip.auth import resolve_url_scheme

            resolve_url_scheme(
                pc, insecure=config.insecure, ca_bundle=config.ca_bundle, proxy=config.proxy
            )
            if name == "connect":
                client: ConnectClient | WorkbenchClient | PackageManagerClient = ConnectClient(
                    pc.url,
                    pc.api_key,  # type: ignore[attr-defined]
                    proxy=config.proxy,
                )
            elif name == "workbench":
                client = WorkbenchClient(
                    pc.url,
                    pc.api_key,  # type: ignore[attr-defined]
                    proxy=config.proxy,
                )
            else:
                client = PackageManagerClient(
                    pc.url,
                    pc.token,  # type: ignore[attr-defined]
                    proxy=config.proxy,
                )
            http_status = client.health()
            state = "ok" if http_status < 400 else "fail"
            products[name] = {
                "configured": True,
                "url": pc.url,
                "http_status": http_status,
                "state": state,
            }
        except Exception as e:  # noqa: BLE001
            products[name] = {
                "configured": True,
                "url": pc.url,
                "state": "fail",
                "detail": str(e),
            }

    all_ok = all(p["state"] in ("ok", "skip") for p in products.values())
    outcome = "ok" if all_ok else "fail"
    exit_status = 0 if all_ok else 1
    return {"products": products, "outcome": outcome, "exit_status": exit_status}


def run_status(args: argparse.Namespace) -> None:
    """Run preflight health checks against each configured product."""
    from vip.config import load_config

    config = load_config(args.config)
    data = _collect_status(config)

    if getattr(args, "json", False):
        print(json.dumps(data))
    else:
        for name, product in data["products"].items():
            state = product["state"]
            if state == "skip":
                detail = product.get("detail", "not configured")
            elif "http_status" in product:
                detail = f"HTTP {product['http_status']}"
            else:
                detail = product.get("detail", "")
            print(f"  {state.upper():4s}  {name:20s}  {detail}")

    sys.exit(data["exit_status"])
