"""Fixtures for plugin integration selftests."""

from __future__ import annotations

import pytest


@pytest.fixture
def selftest_pytester(pytester):
    """Pytester fixture pre-configured with VIP installed."""
    # Write a minimal vip.toml that has no products configured so all
    # product-marked tests get skipped.
    pytester.makefile(".toml", vip='[general]\ndeployment_name = "Selftest"')
    return pytester
