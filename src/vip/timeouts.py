"""Global timeout scale helper for VIP.

A single env var, ``VIP_TIMEOUT_SCALE``, multiplies every genuine operation
timeout in VIP.  Setting it at module-import time is the only mechanism that
can reach the Playwright/IdP constants in conftest and idp.py before any
pytest fixture or config-file parse occurs.

Usage::

    VIP_TIMEOUT_SCALE=3 vip verify --connect-url https://connect.example.com

Values ≤ 0 or non-numeric fall back to 1.0 (no scaling).
"""

from __future__ import annotations

import os


def timeout_scale() -> float:
    """Global multiplier for operation timeouts, from VIP_TIMEOUT_SCALE.

    Returns 1.0 when unset or invalid. Read fresh on each call so it works
    both at module-import time (Playwright/IdP constants) and at call time
    (auth flows, clients). Values <= 0 are ignored (fall back to 1.0).
    """
    raw = os.environ.get("VIP_TIMEOUT_SCALE")
    if raw is None:
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0


def scaled(value: float) -> float:
    """Multiply a timeout (seconds or milliseconds) by the global scale."""
    return value * timeout_scale()
