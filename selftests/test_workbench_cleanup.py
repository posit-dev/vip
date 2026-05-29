"""Selftests for WorkbenchClient VIP-session cleanup helpers.

No real network connections are made: the WorkbenchClient's internal
httpx client is replaced with one backed by httpx.MockTransport.
"""

from __future__ import annotations

import pytest

from vip.clients.workbench import is_vip_session


@pytest.mark.parametrize(
    "label, expected",
    [
        ("VIP test_ide_launch.py - gw0-123", True),
        ("VIP foo", True),
        ("_vip_cap_1700000000_default_0", True),
        ("My analysis", False),
        ("vip lowercase no space", False),
        ("", False),
    ],
)
def test_is_vip_session(label, expected):
    assert is_vip_session(label) is expected
